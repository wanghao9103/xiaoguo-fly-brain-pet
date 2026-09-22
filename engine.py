"""Persistent body state and online action learning, separate from the UI.

Need variables and intrinsic reward equations are designed simulation rules.
FlyBrain learns action values; neither these variables nor animations establish
subjective feelings. No screen text, key presses, or private files are observed.
"""
from datetime import datetime, timezone
import math
from brain import ACTIONS, ACTION_LABELS, FlyBrain

DECISION_SECONDS = 6.0


def bounded(value, low=0.0, high=1.0):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("State values must be finite.")
    return min(high, max(low, value))


class PetEngine:
    def __init__(self, seed=42):
        self.brain = FlyBrain(seed=seed)
        self.body = {"energy": .8, "satiety": .75, "social": .55, "curiosity": .65,
                     "recent_touch": 0.0, "recent_food": 0.0, "idle": 0.0,
                     "age_seconds": 0.0}
        self.settings = {"paused": False, "frozen": False, "stay": False}
        self.action = "rest"
        self.pending_features = None
        self.decision_elapsed = 0.0
        self.memory = []
        self.position = None
        self.sessions = 0
        self.last_feedback = None
        self.message = "你好，我是小果"
        self.last_observation = {}
        self._game_features = None  # transient: a restarted app must not replay a game reward
        self.last_decision = None  # exact decision-time evidence, not a generated inner monologue

    def remember(self, kind, text, **details):
        record = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  "kind": kind, "text": text}
        record.update(details)
        self.memory.append(record)
        self.memory = self.memory[-60:]

    def start_session(self):
        self.sessions += 1
        self.remember("session", f"第 {self.sessions} 次见面，继续使用已保存的行为偏好。")

    def features(self, observation=None):
        observation = observation or self.last_observation
        values = [
            self.body["energy"], self.body["satiety"], self.body["social"],
            self.body["curiosity"], bounded(observation.get("cursor_near", .0)),
            bounded(observation.get("cursor_slow", 1.0)),
            bounded(observation.get("edge_near", .0)),
            self.body["recent_touch"], self.body["recent_food"],
            bounded(self.body["idle"] / 120.0),
            bounded(observation.get("daylight", .5)),
            1.0 if self.settings["stay"] else .0,
        ]
        return [part for value in values for part in (value, 1.0 - value)]

    @staticmethod
    def intrinsic_reward(action, features):
        """A designed immediate utility signal, not a sensed emotion or long-term return."""
        energy, social, curiosity = features[0], features[4], features[6]
        near, slow = features[8], features[10]
        rewards = {
            "rest": .85 * (1.0 - energy) - .35 * energy,
            "wander": .60 * curiosity + .20 * energy - .30,
            "approach": .75 * (1.0 - social) * (.3 + .7 * near) - .25 * (1.0 - slow),
            "play": .75 * curiosity * energy - .40 * (1.0 - energy) - .12,
        }
        return bounded(rewards[action], -1, 1)

    def decide(self, observation=None):
        features = self.features(observation)
        probabilities = self.brain.probabilities(features)
        # Low-energy rest is selected by a protection rule; its outcome may still train the readout.
        protected = self.body["energy"] < .08
        self.action = "rest" if protected else self.brain.choose(features)
        self.last_decision = {"source": "protection" if protected else "network",
                              "action": self.action, "features": features[:],
                              "probabilities": dict(zip(ACTIONS, probabilities))}
        self.pending_features = features
        self.decision_elapsed = 0.0
        self.message = {"rest": "让我歇一会儿", "wander": "我去转转",
                        "approach": "过来看看你", "play": "活动一下翅膀"}[self.action]
        return self.action

    def describe_decision(self, compact=False):
        decision = self.last_decision
        if decision is None:
            return "等待第一次选择"
        if decision["source"] == "protection":
            return "精力低，按保护规则休息"
        if decision["source"] == "interaction":
            return "按你的指令开始玩耍"
        action = ACTION_LABELS[decision["action"]]
        probability = decision["probabilities"][decision["action"]]
        return f"自己选：{action} · {probability:.0%}" if compact else f"自主选择：{action}（选择时倾向 {probability:.0%}，含随机探索）"

    def advance(self, seconds, observation=None, allow_decisions=True):
        seconds = bounded(seconds, 0, 2)  # Suspend/resume cannot simulate hours of deprivation.
        if observation is not None:
            self.last_observation = dict(observation)
        if self.settings["paused"]:
            return False
        if self.pending_features is None:
            self.decide()
        b = self.body
        b["age_seconds"] += seconds
        b["idle"] = min(1200, b["idle"] + seconds)
        b["recent_touch"] = max(0, b["recent_touch"] - seconds / 90)
        b["recent_food"] = max(0, b["recent_food"] - seconds / 120)
        b["satiety"] = max(0, b["satiety"] - .00028 * seconds)
        b["social"] = max(0, b["social"] - .00065 * seconds)
        b["curiosity"] = min(1, b["curiosity"] + .0010 * seconds)
        if self.action == "rest":
            b["energy"] = min(1, b["energy"] + .0035 * seconds)
        else:
            b["energy"] = max(0, b["energy"] - (.0014 if self.action == "play" else .0007) * seconds)
        if self.action in ("wander", "play"):
            b["curiosity"] = max(0, b["curiosity"] - .0022 * seconds)
        if not allow_decisions:
            return False
        self.decision_elapsed += seconds
        if self.decision_elapsed >= DECISION_SECONDS:
            if not self.settings["frozen"]:
                self.brain.learn(self.pending_features, self.action,
                                 self.intrinsic_reward(self.action, self.pending_features),
                                 source="intrinsic")
            self.decide()
            return True
        return False

    def begin_game(self):
        if self.settings["paused"] or self.body["energy"] < .08:
            return False
        if self._game_features is not None:
            return True
        self._game_features = self.features()
        self.pending_features = self._game_features[:]
        self.action = "play"  # explicitly requested action, not a sampled autonomous choice
        self.last_decision = {"source": "interaction", "action": "play",
                              "features": self._game_features[:], "probabilities": None}
        self.decision_elapsed = 0.0
        self.body["idle"] = 0.0
        self.remember("game_start", "开始追鼠标小游戏。", action="play")
        return True

    def finish_game(self, catches, cancelled=False):
        if type(catches) is not int or not 0 <= catches <= 3:
            raise ValueError("Expected 0..3 catches.")
        if self._game_features is None:
            return None
        features, self._game_features = self._game_features, None
        reward = min(.9, .3 * catches)
        result = None
        if not cancelled and not self.settings["frozen"] and not self.settings["paused"]:
            result = self.brain.learn(features, "play", reward, source="intrinsic")
        if not cancelled:
            self.body["social"] = min(1, self.body["social"] + .04 * catches)
            self.body["curiosity"] = max(0, self.body["curiosity"] - .06 * catches)
        text = "小游戏已取消" if cancelled else f"追鼠标结束，接近目标 {catches}/3 次"
        self.remember("game_end", text, action="play", reward=reward, learned=result is not None)
        self.pending_features = None
        self.decision_elapsed = 0.0
        return result

    def capture_feedback_context(self):
        return {"action": self.action,
                "features": list(self.pending_features if self.pending_features is not None else self.features())}

    def interact(self, kind, context=None):
        if kind not in ("pet", "feed", "praise", "discourage"):
            raise ValueError("Unknown interaction.")
        if context is not None:
            if not isinstance(context, dict) or set(context) != {"action", "features"} or context["action"] not in ACTIONS:
                raise ValueError("Invalid feedback context.")
            self.brain.encode(context["features"])
            action, feedback_features = context["action"], context["features"]
        else:
            if self.pending_features is None:
                if self.settings["paused"]:
                    self.pending_features = self.features()
                else:
                    self.decide()
            action, feedback_features = self.action, self.pending_features
        reward = {"pet": .8, "feed": .6, "praise": 1.0, "discourage": -1.0}[kind]
        labels = {"pet": "抚摸", "feed": "喂食", "praise": "鼓励", "discourage": "制止"}
        if kind == "pet":
            self.body["social"] = min(1, self.body["social"] + .18)
            self.body["recent_touch"] = 1.0
            self.message = "收到你的抚摸啦"
        elif kind == "feed":
            self.body["satiety"] = min(1, self.body["satiety"] + .22)
            self.body["energy"] = min(1, self.body["energy"] + .06)
            self.body["recent_food"] = 1.0
            self.message = "谢谢这份小点心"
        elif kind == "praise":
            self.message = "记住这次鼓励了"
        else:
            self.message = "好，我调整一下"
        self.body["idle"] = 0.0
        # Feedback is credited to the state at action selection, not the post-feed state.
        result = None
        if not self.settings["frozen"] and not self.settings["paused"]:
            result = self.brain.learn(feedback_features, action, reward, source="user")
        else:
            self.message = "收到啦，先歇一会儿" if self.settings["paused"] else "收到啦，当前不学新习惯"
        self.last_feedback = {"kind": kind, "action": action, "reward": reward,
                              "learned": result is not None}
        text = f"{labels[kind]} · 当时正在{ACTION_LABELS[action]}"
        if result is None:
            text += "（权重未更新）"
        self.remember(kind, text, action=action, reward=reward, learned=result is not None)
        return result

    def to_dict(self):
        return {"schema_version": 1, "brain": self.brain.to_dict(), "body": dict(self.body),
                "settings": dict(self.settings), "action": self.action,
                "pending_features": self.pending_features, "decision_elapsed": self.decision_elapsed,
                "memory": list(self.memory), "position": self.position, "sessions": self.sessions}

    @classmethod
    def from_dict(cls, data):
        fields = {"schema_version", "brain", "body", "settings", "action", "pending_features",
                  "decision_elapsed", "memory", "position", "sessions"}
        if (not isinstance(data, dict) or set(data) != fields or
                type(data.get("schema_version")) is not int or data["schema_version"] != 1):
            raise ValueError("Unsupported pet save format.")
        obj = cls()
        obj.brain = FlyBrain.from_dict(data["brain"])
        body = data["body"]
        if not isinstance(body, dict) or set(body) != set(obj.body):
            raise ValueError("Invalid body fields.")
        for key, value in body.items():
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
                raise ValueError("Invalid body value.")
            maximum = 1e12 if key == "age_seconds" else 1200 if key == "idle" else 1
            if not 0 <= value <= maximum:
                raise ValueError("Body value outside bounds.")
        obj.body = dict(body)
        settings = data["settings"]
        if not isinstance(settings, dict) or set(settings) != set(obj.settings):
            raise ValueError("Invalid settings.")
        if any(type(value) is not bool for value in settings.values()):
            raise ValueError("Settings must be boolean.")
        obj.settings = dict(settings)
        if data["action"] not in ACTIONS:
            raise ValueError("Invalid action.")
        obj.action = data["action"]
        pending = data.get("pending_features")
        if pending is not None:
            obj.brain.encode(pending)  # validates dimensions and finite feature values
            obj.pending_features = list(pending)
        elapsed = data.get("decision_elapsed", 0.0)
        if isinstance(elapsed, bool) or not isinstance(elapsed, (float, int)) or not math.isfinite(elapsed) or not 0 <= elapsed <= 6:
            raise ValueError("Invalid decision clock.")
        obj.decision_elapsed = elapsed
        memory = data.get("memory", [])
        if not isinstance(memory, list) or len(memory) > 60:
            raise ValueError("Invalid memory.")
        allowed = {"at", "kind", "text", "action", "reward", "learned"}
        for item in memory:
            if not isinstance(item, dict) or not set(item).issubset(allowed):
                raise ValueError("Invalid memory item.")
            if any(not isinstance(item.get(k), str) or len(item[k]) > 400 for k in ("at", "kind", "text")):
                raise ValueError("Invalid memory text.")
            if datetime.fromisoformat(item["at"]).tzinfo is None:
                raise ValueError("Memory timestamps must include a timezone.")
            if "action" in item and item["action"] not in ACTIONS:
                raise ValueError("Invalid memory action.")
            if "reward" in item and (isinstance(item["reward"], bool) or not isinstance(item["reward"], (float, int)) or
                                     not math.isfinite(item["reward"]) or not -1 <= item["reward"] <= 1):
                raise ValueError("Invalid memory reward.")
            if "learned" in item and type(item["learned"]) is not bool:
                raise ValueError("Invalid learning flag.")
        obj.memory = [dict(item) for item in memory]
        sessions = data.get("sessions", 0)
        if type(sessions) is not int or not 0 <= sessions <= 10**9:
            raise ValueError("Invalid session count.")
        obj.sessions = sessions
        position = data.get("position")
        if position is not None and (not isinstance(position, list) or len(position) != 2 or
                                   any(type(v) is not int or abs(v) > 100000 for v in position)):
            raise ValueError("Invalid position.")
        obj.position = position
        return obj
