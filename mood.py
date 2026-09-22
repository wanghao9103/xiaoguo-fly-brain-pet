"""Read-only simulated moods derived from saved state; not subjective feelings.

No timers, rewards, action changes, or persistent fields are introduced here.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Mood:
    code: str
    label: str
    motion: float
    wing: float
    droop: float = 0
    message: str = ""
    since: float = 0


MOODS = {
    "calm": Mood("calm", "平静", 1.0, 1.0),
    "content": Mood("content", "开心", 1.0, 1.1),
    "curious": Mood("curious", "好奇", .85, .85, -1, "看看周围有什么", 45),
    "bored": Mood("bored", "无聊", .55, .45, 6, "我先发会儿呆", 120),
    "sleepy": Mood("sleepy", "困倦", .30, .25, 9, "有点困啦", 300),
    "tearful": Mood("tearful", "委屈", .25, .28, 11, "我先安静一会儿", 600),
    "playful": Mood("playful", "兴奋", 1.0, 1.4),
    "paused": Mood("paused", "暂停", 0.0, 0.0),
}


def select_mood(body, paused=False, playing=False):
    if paused:
        return MOODS["paused"]
    if playing:
        return MOODS["playful"]
    idle, energy = body["idle"], body["energy"]
    recent = max(body["recent_touch"], body["recent_food"])
    if energy < .08:
        return MOODS["sleepy"]
    if idle < 30 and recent >= .65:
        return MOODS["content"]
    if idle >= 600:
        return MOODS["tearful"]
    if idle >= 300 or energy < .22:
        return MOODS["sleepy"]
    if idle >= 120:
        return MOODS["bored"]
    if idle >= 45:
        return MOODS["curious"]
    return MOODS["calm"]


def ambient_message(mood, idle):
    """Within a mood phase, show a small bubble for three seconds every 90 idle seconds."""
    if mood.message and idle >= mood.since and (idle - mood.since) % 90 < 3:
        return mood.message
    return ""


def tear_phases(body):
    """Two small drops during short bursts; the running clock does not saturate like idle."""
    if select_mood(body).code != "tearful":
        return ()
    age = body["age_seconds"]
    if body["idle"] >= 604 and age % 30 >= 4:
        return ()
    phase = (age % 1.4) / 1.4
    return (phase, (phase + .5) % 1.0)
