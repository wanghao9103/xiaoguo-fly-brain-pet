"""A small mushroom-body-inspired contextual bandit, using Python only.

Fixed sparse positive projection -> winner-take-all -> learned action values.
Random positive strengths are an engineering choice that diversifies responses;
they are not measured fruit-fly synaptic weights. Sparse input connectivity and
activity do not, by themselves, demonstrate a speed or energy advantage.
This is a structural analogy, not a connectome simulation, consciousness model,
or long-horizon reinforcement learner. Rewards refer to the supplied context
and action; the UI owns temporal credit assignment and persistent storage.
"""

from __future__ import annotations

import math
import random
from typing import Any, Sequence

ACTIONS = ("rest", "wander", "approach", "play")
ACTION_LABELS = {"rest": "休息", "wander": "探索", "approach": "靠近", "play": "玩耍"}
FEATURE_NAMES = (
    "energy", "low_energy", "satiety", "hunger", "social", "low_social",
    "curiosity", "low_curiosity", "cursor_near", "cursor_far",
    "cursor_slow", "cursor_fast", "edge_near", "edge_far",
    "recent_touch", "no_recent_touch", "recent_food", "no_recent_food",
    "time_idle", "recently_active", "daylight", "night", "calm", "aroused",
)
SCHEMA_VERSION = 1
MODEL_KIND = "fly-mushroom-body-contextual-bandit"


def _number(value: Any, name: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(result) or not low <= result <= high:
        raise ValueError(f"{name} must be finite and in [{low}, {high}]")
    return result


def _integer(value: Any, name: str, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer in [{low}, {high}]")
    return value


def _list(value: Any, name: str, length: int) -> list:
    if not isinstance(value, list) or len(value) != length:
        raise ValueError(f"{name} must be a list of length {length}")
    return value


def _rng_from_json(value: Any) -> tuple:
    """Validate MT19937 data before passing it to random.Random.setstate."""
    state = _list(value, "rng_state", 3)
    _integer(state[0], "rng version", 3, 3)
    words = _list(state[1], "rng words", 625)
    for i, word in enumerate(words[:-1]):
        _integer(word, f"rng word {i}", 0, 2**32 - 1)
    _integer(words[-1], "rng position", 0, 624)
    gaussian = state[2]
    if gaussian is not None:
        gaussian = _number(gaussian, "rng gaussian", -1e100, 1e100)
    return (3, tuple(words), gaussian)


class FlyBrain:
    """Online action-value learner with a reproducible sparse representation.

    Input order is FEATURE_NAMES. Features must be finite values in [0, 1].
    Connections and connection_weights are fixed after initialization. Only
    the selected action's row in weights changes during learn(). No bias term
    is used; a zero feature vector therefore always produces uniform choices.
    """

    def __init__(self, seed: int = 42, width: int = 384, fan_in: int = 6,
                 k: int = 24):
        self.seed = _integer(seed, "seed", -(2**63), 2**63 - 1)
        self.width = _integer(width, "width", 1, 8192)
        self.fan_in = _integer(fan_in, "fan_in", 1, len(FEATURE_NAMES))
        self.k = _integer(k, "k", 1, self.width)
        self.learning_rate = 0.20
        self.decay = 0.0002
        self.weight_limit = 3.0
        self.temperature = 0.45
        self.exploration = 0.08
        self.rng = random.Random(self.seed)
        self.connections = [
            self.rng.sample(range(len(FEATURE_NAMES)), self.fan_in)
            for _ in range(self.width)
        ]
        self.connection_weights = [
            [self.rng.uniform(0.5, 1.5) / self.fan_in
             for _ in range(self.fan_in)]
            for _ in range(self.width)
        ]
        self.weights = [[0.0] * self.width for _ in ACTIONS]
        self.updates = 0
        self.user_updates = 0

    def encode(self, features: Sequence[float]) -> list[float]:
        if isinstance(features, (str, bytes)):
            raise ValueError("features must be 24 numeric values")
        try:
            values = list(features)
        except TypeError as exc:
            raise ValueError("features must be 24 numeric values") from exc
        if len(values) != len(FEATURE_NAMES):
            raise ValueError(f"features must have length {len(FEATURE_NAMES)}")
        values = [_number(value, FEATURE_NAMES[i], 0, 1)
                  for i, value in enumerate(values)]
        activations = [
            max(0.0, sum(values[i] * w for i, w in zip(indices, strengths)))
            for indices, strengths in zip(self.connections, self.connection_weights)
        ]
        # A deterministic secondary index also makes all ties reproducible.
        winners = sorted(range(self.width), key=lambda i: (-activations[i], i))[:self.k]
        norm = math.sqrt(sum(activations[i] ** 2 for i in winners))
        encoded = [0.0] * self.width
        if norm:
            for i in winners:
                encoded[i] = activations[i] / norm
        return encoded

    def scores(self, features: Sequence[float]) -> list[float]:
        encoded = self.encode(features)
        return [sum(w * h for w, h in zip(row, encoded)) for row in self.weights]

    def probabilities(self, features: Sequence[float]) -> list[float]:
        scaled = [score / self.temperature for score in self.scores(features)]
        peak = max(scaled)
        exponents = [math.exp(score - peak) for score in scaled]
        total = sum(exponents)
        return [(1 - self.exploration) * value / total + self.exploration / len(ACTIONS)
                for value in exponents]

    def choose(self, features: Sequence[float]) -> str:
        probabilities = self.probabilities(features)
        draw = self.rng.random()
        cumulative = 0.0
        for action, probability in zip(ACTIONS, probabilities):
            cumulative += probability
            if draw < cumulative:
                return action
        return ACTIONS[-1]

    def learn(self, features: Sequence[float], action: str, reward: float,
              source: str = "intrinsic") -> dict[str, float]:
        """One bounded prediction-error update; weight_change is its L2 norm.

        This is supervised reward fitting for an action-conditioned context.
        A user reward only affects the row of the action passed by the UI.
        It neither redistributes feedback to other actions nor searches for
        causes across time. Decay and clipping bound accumulated parameters.
        """
        if action not in ACTIONS:
            raise ValueError(f"action must be one of {ACTIONS}")
        reward = _number(reward, "reward", -1, 1)
        if source not in ("intrinsic", "user"):
            raise ValueError("source must be 'intrinsic' or 'user'")
        encoded = self.encode(features)
        row = self.weights[ACTIONS.index(action)]
        prediction = sum(w * h for w, h in zip(row, encoded))
        error = reward - prediction
        squared_change = 0.0
        for i, activation in enumerate(encoded):
            previous = row[i]
            updated = previous * (1 - self.decay) + self.learning_rate * error * activation
            row[i] = min(self.weight_limit, max(-self.weight_limit, updated))
            squared_change += (row[i] - previous) ** 2
        self.updates += 1
        if source == "user":
            self.user_updates += 1
        return {"prediction": prediction, "error": error,
                "weight_change": math.sqrt(squared_change)}

    def to_dict(self) -> dict[str, Any]:
        """Return detached, JSON-only data including actual projection and RNG."""
        rng_state = self.rng.getstate()
        return {
            "schema": SCHEMA_VERSION,
            "kind": MODEL_KIND,
            "actions": list(ACTIONS),
            "feature_names": list(FEATURE_NAMES),
            "config": {
                "seed": self.seed, "width": self.width, "fan_in": self.fan_in,
                "k": self.k, "learning_rate": self.learning_rate,
                "decay": self.decay, "weight_limit": self.weight_limit,
                "temperature": self.temperature, "exploration": self.exploration,
            },
            "connections": [row[:] for row in self.connections],
            "connection_weights": [row[:] for row in self.connection_weights],
            "weights": [row[:] for row in self.weights],
            "updates": self.updates,
            "user_updates": self.user_updates,
            "rng_state": [rng_state[0], list(rng_state[1]), rng_state[2]],
        }

    @classmethod
    def from_dict(cls, data: Any) -> "FlyBrain":
        """Load validated data only. No pickle, eval, imports, or executable hooks."""
        if not isinstance(data, dict):
            raise ValueError("brain state must be an object")
        required = {"schema", "kind", "actions", "feature_names", "config",
                    "connections", "connection_weights", "weights", "updates",
                    "user_updates", "rng_state"}
        if set(data) != required:
            raise ValueError("brain state has missing or unknown fields")
        _integer(data["schema"], "schema", SCHEMA_VERSION, SCHEMA_VERSION)
        if data["kind"] != MODEL_KIND:
            raise ValueError("unsupported model kind")
        if data["actions"] != list(ACTIONS) or data["feature_names"] != list(FEATURE_NAMES):
            raise ValueError("action or feature order does not match this model")
        config = data["config"]
        config_names = {"seed", "width", "fan_in", "k", "learning_rate", "decay",
                        "weight_limit", "temperature", "exploration"}
        if not isinstance(config, dict) or set(config) != config_names:
            raise ValueError("invalid model configuration fields")
        seed = _integer(config["seed"], "seed", -(2**63), 2**63 - 1)
        width = _integer(config["width"], "width", 1, 8192)
        fan_in = _integer(config["fan_in"], "fan_in", 1, len(FEATURE_NAMES))
        k = _integer(config["k"], "k", 1, width)
        learning_rate = _number(config["learning_rate"], "learning_rate", 0.000001, 1)
        decay = _number(config["decay"], "decay", 0, 0.01)
        weight_limit = _number(config["weight_limit"], "weight_limit", 0.01, 10)
        temperature = _number(config["temperature"], "temperature", 0.05, 5)
        exploration = _number(config["exploration"], "exploration", 0.001, 0.5)
        connections = []
        for unit, row in enumerate(_list(data["connections"], "connections", width)):
            row = _list(row, f"connections[{unit}]", fan_in)
            checked = [_integer(i, "connection index", 0, len(FEATURE_NAMES) - 1) for i in row]
            if len(set(checked)) != fan_in:
                raise ValueError("connections within a unit must be distinct")
            connections.append(checked)
        projection = []
        for unit, row in enumerate(_list(data["connection_weights"], "connection_weights", width)):
            row = _list(row, f"connection_weights[{unit}]", fan_in)
            projection.append([_number(w, "projection weight", 0.000001, 10) for w in row])
        weights = []
        for action, row in enumerate(_list(data["weights"], "weights", len(ACTIONS))):
            row = _list(row, f"weights[{action}]", width)
            weights.append([_number(w, "readout weight", -weight_limit, weight_limit) for w in row])
        updates = _integer(data["updates"], "updates", 0, 2**63 - 1)
        user_updates = _integer(data["user_updates"], "user_updates", 0, updates)
        rng_state = _rng_from_json(data["rng_state"])
        brain = cls(seed=seed, width=width, fan_in=fan_in, k=k)
        brain.learning_rate, brain.decay = learning_rate, decay
        brain.weight_limit = weight_limit
        brain.temperature, brain.exploration = temperature, exploration
        brain.connections, brain.connection_weights, brain.weights = connections, projection, weights
        brain.updates, brain.user_updates = updates, user_updates
        brain.rng.setstate(rng_state)
        return brain
