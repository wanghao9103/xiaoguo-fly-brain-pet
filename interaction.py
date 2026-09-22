"""Transient interaction clocks, independent of saved learning weights and the GUI."""
from dataclasses import dataclass
import math


@dataclass
class InteractionState:
    effect: str = ""
    effect_left: float = 0.0
    effect_duration: float = 0.0
    game_left: float = 0.0
    catches: int = 0
    catch_ready: bool = False

    @property
    def playing(self):
        return self.game_left > 0

    @property
    def progress(self):
        return 1 - self.effect_left / self.effect_duration if self.effect_duration else 1

    def react(self, effect, seconds=2.5):
        self.effect = effect
        self.effect_left = self.effect_duration = seconds

    def start_game(self):
        self.game_left = 12.0
        self.catches = 0
        self.catch_ready = False
        self.react("play", 1.0)

    def cancel_game(self):
        self.game_left = 0.0
        self.catch_ready = False

    def advance(self, seconds, distance=math.inf, paused=False):
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("Invalid interaction delta.")
        if paused:
            return []
        self.effect_left = max(0, self.effect_left - seconds)
        if self.effect_left == 0:
            self.effect = ""
        if not self.playing:
            return []
        self.game_left = max(0, self.game_left - seconds)
        events = []
        # A target must move away before another catch; a stationary cursor cannot farm points.
        if distance > 70:
            self.catch_ready = True
        if self.catch_ready and distance < 43 and self.game_left > 0:
            self.catches += 1
            self.catch_ready = False
            events.append("catch")
        if self.catches >= 3 or self.game_left == 0:
            self.game_left = 0
            events.append("finish")
        return events
