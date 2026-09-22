"""Independent board-game session: rules, search teacher and fly-style move memory."""
import copy
from datetime import datetime, timezone
import threading

from chess_memory import ChessMemoryStore
from gomoku import GomokuGame, FEATURE_LABELS as GOMOKU_FEATURES
from xiangqi import XiangqiGame, FEATURE_LABELS as XIANGQI_FEATURES

KINDS = {"gomoku": "五子棋", "xiangqi": "中国象棋"}
FACTORIES = {"gomoku": GomokuGame, "xiangqi": XiangqiGame}
FEATURES = {"gomoku": GOMOKU_FEATURES, "xiangqi": XIANGQI_FEATURES}


class GamesSession:
    def __init__(self, directory, on_event=None):
        self.lock = threading.RLock()
        self.store = ChessMemoryStore(directory, FEATURES)
        self.on_event = on_event
        self.kind = "gomoku"
        self.game = GomokuGame()
        self.human_side = 1
        self.depth = 2
        self.learning = True
        self.revision = 0
        self.trace = []
        self.analysis = None
        self.coach = None
        self.recorded = False
        self.closed = False

    def snapshot(self):
        data = self.game.snapshot()
        data.update({"human_side": self.human_side, "depth": self.depth, "learning": self.learning,
                     "revision": self.revision, "legal_moves": self.game.legal_moves(),
                     "memory": self.store.models[self.kind].stats(),
                     "saved_games": sum(record["kind"] == self.kind for record in self.store.records),
                     "analysis": copy.deepcopy(self.analysis), "coach": copy.deepcopy(self.coach),
                     "warning": self.store.warning,
                     "can_undo": self.game.winner is None and len(self.game.history) >= (2 if self.human_side == 1 else 3)})
        if "reason" not in data:
            data["reason"] = getattr(self.game, "reason", None) or ("five" if self.game.winner not in (None, 0) else "full" if self.game.winner == 0 else None)
        return data

    def _notify(self, events):
        if self.on_event:
            for event in events:
                try:
                    self.on_event(event)  # caller queues data; it must not touch Tk from this thread
                except Exception:
                    pass

    def _rank(self):
        ranked = self.game.rank_moves(depth=self.depth, limit=12)
        forced = [row for row in ranked if row["forced"]]
        if forced:
            ranked = forced
        if not ranked:
            raise ValueError("当前没有可走棋步。")
        low, high = min(row["score"] for row in ranked), max(row["score"] for row in ranked)
        model = self.store.models[self.kind]
        rows, examples = [], []
        for row in ranked:
            feature_values = self.game.move_features(row["move"])
            target = .9 if forced else (1.8 * (row["score"] - low) / (high - low) - .9 if high > low else 0.0)
            neural = model.predict(feature_values)
            mixed = .7 * target + .3 * max(-1, min(1, neural)) if self.learning else target
            item = {**row, "features": feature_values, "teacher_value": target,
                    "neural_value": neural, "combined_value": mixed}
            rows.append(item)
            if forced or high > low:
                examples.append((feature_values, target))
        return rows, examples

    def _ai_move(self, events):
        if self.game.winner is not None or self.game.turn == self.human_side:
            return
        rows, examples = self._rank()
        chosen = max(rows, key=lambda row: (row["combined_value"], row["score"]))
        model = self.store.models[self.kind]
        lesson = model.learn_batch(examples, source="teacher") if self.learning and examples else None
        self.game.play(chosen["move"])
        self.trace.append({"ply": len(self.game.history), "features": chosen["features"]})
        self.analysis = {"move": chosen["move"], "source": "tactical" if chosen["forced"] else "hybrid" if self.learning else "search",
                         "teacher_value": chosen["teacher_value"], "neural_before": chosen["neural_value"],
                         "neural_after": model.predict(chosen["features"]), "lesson": lesson}
        events.append({"kind": "ai_move", "game": self.kind, "message": "轮到你啦，看看这一步"})
        self._check_limit()

    def _check_limit(self):
        if self.game.winner is None and len(self.game.history) >= 400:
            self.game.winner = 0
            self.game.reason = "move_limit"

    def _finish(self, events):
        if self.game.winner is None or self.recorded:
            return
        winner = self.game.winner
        reward = 0.0 if winner == 0 else .9 if winner == -self.human_side else -.9
        if self.learning and self.trace:
            examples = [(item["features"], reward * (.90 ** index))
                        for index, item in enumerate(reversed(self.trace[-16:]))]
            self.store.models[self.kind].learn_batch(examples, source="outcome")
        self.recorded = True
        state = self.game.snapshot()
        reason = state.get("reason") or getattr(self.game, "reason", None) or ("five" if winner else "full")
        self.store.records.append({"kind": self.kind, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                   "human_side": self.human_side, "winner": winner, "reason": reason,
                                   "moves": [record["move"][:] for record in self.game.history]})
        self.store.records = self.store.records[-30:]
        message = "平局，一起再试试" if winner == 0 else "你赢啦，厉害！" if winner == self.human_side else "这一局我赢啦，再来？"
        events.append({"kind": "finish", "game": self.kind, "message": message,
                       "result": "draw" if winner == 0 else "human_win" if winner == self.human_side else "ai_win"})

    def command(self, name, payload):
        if not isinstance(payload, dict):
            raise ValueError("请求必须是对象。")
        with self.lock:
            if self.closed:
                raise RuntimeError("棋桌已关闭，请重新打开。")
            revision = payload.get("revision")
            if type(revision) is not int or revision != self.revision:
                raise ValueError("棋局已经变化，请刷新后再操作。")
            before = (self.game.clone(), self.kind, self.human_side, self.depth, self.learning,
                      copy.deepcopy(self.trace), copy.deepcopy(self.analysis), copy.deepcopy(self.coach),
                      self.recorded, copy.deepcopy(self.store.models), copy.deepcopy(self.store.records))
            events = []
            try:
                if name == "new":
                    kind = payload.get("kind", self.kind)
                    side = payload.get("human_side", 1)
                    depth = payload.get("depth", 2)
                    learning = payload.get("learning", True)
                    if kind not in KINDS or type(side) is not int or side not in (-1, 1) or type(depth) is not int or depth not in (1, 2) or type(learning) is not bool:
                        raise ValueError("棋种、先后手或难度不正确。")
                    self.kind, self.human_side, self.depth, self.learning = kind, side, depth, learning
                    self.game = FACTORIES[kind]()
                    self.trace, self.analysis, self.coach = [], None, None
                    self.recorded = False
                    events.append({"kind": "start", "game": kind, "message": f"来下{KINDS[kind]}吧"})
                    self._ai_move(events)
                elif name == "move":
                    if self.game.winner is not None:
                        raise ValueError("本局已经结束，请重新开局。")
                    if self.game.turn != self.human_side:
                        raise ValueError("请等待小果落子。")
                    self.game.play(payload.get("move"))
                    self.coach = None
                    events.append({"kind": "human_move", "game": self.kind, "message": "这步有意思，让我看看"})
                    self._check_limit()
                    self._ai_move(events)
                    self._finish(events)
                elif name == "undo":
                    if not self.snapshot()["can_undo"]:
                        raise ValueError("现在不能悔棋。终局请重新开局。")
                    self.game.undo(2)
                    self.trace = [item for item in self.trace if item["ply"] <= len(self.game.history)]
                    self.analysis, self.coach = None, None
                    events.append({"kind": "undo", "game": self.kind, "message": "好，这一回合重新想想"})
                elif name == "coach":
                    if self.game.winner is not None or not self.learning:
                        raise ValueError("请在进行中的对局开启棋步学习。")
                    rows, examples = self._rank()
                    if examples:
                        lesson = self.store.models[self.kind].learn_batch(examples, "teacher", rounds=5)
                        self.coach = {**lesson, "suggestion": rows[0]["move"],
                                      "note": "已用搜索老师的相对评分练习，评分不是胜率。"}
                    else:
                        self.coach = {"before": 0.0, "after": 0.0, "examples": 0, "rounds": 0,
                                      "suggestion": rows[0]["move"], "note": "这些候选评分相同，暂时没有可区分的示范。"}
                elif name == "learning":
                    enabled = payload.get("enabled")
                    if type(enabled) is not bool:
                        raise ValueError("学习开关必须为布尔值。")
                    self.learning = enabled
                elif name == "resign":
                    if self.game.winner is not None:
                        raise ValueError("本局已经结束。")
                    self.game.winner = -self.human_side
                    self.game.reason = "resign"
                    self._finish(events)
                else:
                    raise ValueError("未知棋桌操作。")
                self.store.save()
                self.revision += 1
            except Exception:
                (self.game, self.kind, self.human_side, self.depth, self.learning,
                 self.trace, self.analysis, self.coach, self.recorded,
                 self.store.models, self.store.records) = before
                raise
            self._notify(events)
            return {"game": self.snapshot()}

    def close(self):
        with self.lock:
            if not self.closed:
                self.closed = True
                self.store.close()
