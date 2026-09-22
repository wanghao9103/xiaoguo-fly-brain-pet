"""Sparse chess move scoring. Legality and search remain separate from learning."""
import copy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import random
import shutil

from storage import InstanceLock, PetStore

SCHEMA = 1
WIDTH, FAN_IN, TOP_K = 384, 6, 24


def bases(values):
    if not isinstance(values, (list, tuple)) or len(values) != 12:
        raise ValueError("Expected 12 chess features.")
    if any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in values):
        raise ValueError("Chess features must be finite values in [0, 1].")
    return [float(v) for v in values]


class MoveMemory:
    def __init__(self, kind, labels, seed=42):
        if kind not in ("gomoku", "xiangqi") or len(labels) != 12:
            raise ValueError("Unknown chess feature schema.")
        self.kind, self.labels, self.seed = kind, list(labels), seed
        rng = random.Random(seed)
        self.connections = [rng.sample(range(24), FAN_IN) for _ in range(WIDTH)]
        self.strengths = [[rng.uniform(.5, 1.5) / FAN_IN for _ in range(FAN_IN)] for _ in range(WIDTH)]
        self.weights = [0.0] * WIDTH
        self.batches = self.teacher_examples = self.outcome_examples = 0

    def encode(self, values):
        raw = bases(values)
        features = [part for value in raw for part in (value, 1 - value)]
        activation = [sum(features[index] * strength for index, strength in zip(indices, strengths))
                      for indices, strengths in zip(self.connections, self.strengths)]
        winners = sorted(range(WIDTH), key=lambda i: (-activation[i], i))[:TOP_K]
        norm = math.sqrt(sum(activation[i] ** 2 for i in winners))
        return [(i, activation[i] / norm) for i in winners] if norm else []

    def predict(self, values):
        return sum(self.weights[i] * value for i, value in self.encode(values))

    def learn_batch(self, examples, source="teacher", rounds=1):
        if source not in ("teacher", "outcome") or type(rounds) is not int or not 1 <= rounds <= 20:
            raise ValueError("Invalid learning request.")
        if not isinstance(examples, list) or not 1 <= len(examples) <= 64:
            raise ValueError("Expected a bounded teaching batch.")
        encoded = []
        for feature_values, target in examples:
            if type(target) not in (int, float) or not math.isfinite(target) or not -1 <= target <= 1:
                raise ValueError("Invalid teacher value.")
            encoded.append((self.encode(feature_values), float(target)))

        def loss():
            return sum((sum(self.weights[i] * x for i, x in h) - y) ** 2 for h, y in encoded) / len(encoded)

        before = loss()
        for _ in range(rounds):
            gradient = [0.0] * WIDTH
            for h, target in encoded:
                error = target - sum(self.weights[i] * x for i, x in h)
                for i, value in h:
                    gradient[i] += error * value / len(encoded)
            self.weights = [max(-3.0, min(3.0, w * .9999 + .35 * gradient[i]))
                            for i, w in enumerate(self.weights)]
            self.batches += 1
            if source == "teacher":
                self.teacher_examples += len(encoded)
            else:
                self.outcome_examples += len(encoded)
        return {"before": before, "after": loss(), "examples": len(encoded) * rounds,
                "rounds": rounds, "source": source}

    def stats(self):
        return {"teacher_examples": self.teacher_examples, "outcome_examples": self.outcome_examples,
                "batches": self.batches, "width": WIDTH, "active": TOP_K}

    def to_dict(self):
        return {"schema": SCHEMA, "kind": self.kind, "labels": self.labels[:], "seed": self.seed,
                "connections": copy.deepcopy(self.connections), "strengths": copy.deepcopy(self.strengths),
                "weights": self.weights[:], "batches": self.batches,
                "teacher_examples": self.teacher_examples, "outcome_examples": self.outcome_examples}

    @classmethod
    def from_dict(cls, data, kind, labels):
        expected = {"schema", "kind", "labels", "seed", "connections", "strengths", "weights",
                    "batches", "teacher_examples", "outcome_examples"}
        if not isinstance(data, dict) or set(data) != expected or type(data["schema"]) is not int or data["schema"] != SCHEMA:
            raise ValueError("Unsupported chess memory.")
        if data["kind"] != kind or data["labels"] != list(labels) or type(data["seed"]) is not int:
            raise ValueError("Chess memory features differ from this version.")
        model = cls(kind, labels, data["seed"])
        for key in ("batches", "teacher_examples", "outcome_examples"):
            if type(data[key]) is not int or not 0 <= data[key] < 2**63:
                raise ValueError("Invalid chess learning counter.")
            setattr(model, key, data[key])
        if not isinstance(data["connections"], list) or len(data["connections"]) != WIDTH:
            raise ValueError("Invalid projection.")
        for row in data["connections"]:
            if not isinstance(row, list) or len(row) != FAN_IN or any(type(v) is not int or not 0 <= v < 24 for v in row) or len(set(row)) != FAN_IN:
                raise ValueError("Invalid sparse connection.")
        if not isinstance(data["strengths"], list) or len(data["strengths"]) != WIDTH:
            raise ValueError("Invalid strengths.")
        for row in data["strengths"]:
            if not isinstance(row, list) or len(row) != FAN_IN or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 < v <= 1 for v in row):
                raise ValueError("Invalid projection strengths.")
        if not isinstance(data["weights"], list) or len(data["weights"]) != WIDTH or any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 3 for v in data["weights"]):
            raise ValueError("Invalid learned weights.")
        model.connections = copy.deepcopy(data["connections"])
        model.strengths = copy.deepcopy(data["strengths"])
        model.weights = data["weights"][:]
        return model


class ChessMemoryStore:
    """Own directory and lock; never opens the desktop pet's body/behavior save."""
    def __init__(self, directory, labels_by_kind):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.labels = labels_by_kind
        self.lock = InstanceLock(self.directory)
        try:
            self.lock.acquire()
        except RuntimeError:
            raise RuntimeError("棋步记忆正在被另一张棋桌使用，请先关闭那张棋桌再打开。") from None
        self.path = self.directory / "memory.json"
        self.backup = self.directory / "memory.backup.json"
        self.models = {kind: MoveMemory(kind, labels, 42 if kind == "gomoku" else 43)
                       for kind, labels in labels_by_kind.items()}
        self.records = []
        self.warning = ""
        try:
            self._load()
        except Exception:
            self.lock.release()
            raise

    def _read(self, path):
        if path.stat().st_size > 4_000_000:
            raise ValueError("Chess memory too large.")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or set(data) != {"schema", "models", "records"} or type(data["schema"]) is not int or data["schema"] != 1:
            raise ValueError("Invalid chess store.")
        if not isinstance(data["models"], dict) or set(data["models"]) != set(self.labels):
            raise ValueError("Missing chess models.")
        models = {kind: MoveMemory.from_dict(data["models"][kind], kind, labels)
                  for kind, labels in self.labels.items()}
        records = data["records"]
        if not isinstance(records, list) or len(records) > 30:
            raise ValueError("Invalid game record count.")
        for record in records:
            if not isinstance(record, dict) or set(record) != {"kind", "at", "human_side", "winner", "reason", "moves"}:
                raise ValueError("Invalid game record.")
            if record["kind"] not in self.labels or type(record["human_side"]) is not int or record["human_side"] not in (-1, 1):
                raise ValueError("Invalid game side.")
            if type(record["winner"]) is not int or record["winner"] not in (-1, 0, 1):
                raise ValueError("Invalid game result.")
            if not isinstance(record["at"], str) or datetime.fromisoformat(record["at"]).tzinfo is None:
                raise ValueError("Invalid game time.")
            if not isinstance(record["reason"], str) or len(record["reason"]) > 80 or not isinstance(record["moves"], list) or len(record["moves"]) > 400:
                raise ValueError("Invalid game moves.")
            size = 2 if record["kind"] == "gomoku" else 4
            for move in record["moves"]:
                if not isinstance(move, list) or len(move) != size or any(type(x) is not int for x in move):
                    raise ValueError("Invalid move record.")
                for i, value in enumerate(move):
                    limit = 15 if size == 2 else (10 if i % 2 == 0 else 9)
                    if not 0 <= value < limit:
                        raise ValueError("Move record out of bounds.")
        return models, records

    def _load(self):
        existing = False
        for path in (self.path, self.backup):
            if not path.exists():
                continue
            existing = True
            try:
                self.models, self.records = self._read(path)
                if path == self.backup:
                    self.warning = "棋步记忆已从上一份备份恢复。"
                return
            except (OSError, ValueError, KeyError, TypeError, OverflowError, RecursionError):
                continue
        if existing:
            raise ValueError("棋步记忆无法读取，原文件已保留。请备份后检查记忆目录。")

    def save(self):
        data = {"schema": 1, "models": {k: v.to_dict() for k, v in self.models.items()},
                "records": self.records[-30:]}
        text = json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        for path in (self.path, self.backup):
            if path.exists():
                try:
                    self._read(path)
                except (OSError, ValueError, KeyError, TypeError, OverflowError, RecursionError):
                    destination = self.directory / (path.stem + ".damaged-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".json")
                    shutil.copy2(path, destination)
        if self.path.exists():
            try:
                self._read(self.path)
            except (OSError, ValueError, KeyError, TypeError, OverflowError, RecursionError):
                pass
            else:
                PetStore.atomic_write(self.backup, self.path.read_text(encoding="utf-8"))
        PetStore.atomic_write(self.path, text)

    def close(self):
        try:
            self.save()
        finally:
            self.lock.release()
