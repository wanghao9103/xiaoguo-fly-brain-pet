"""Interaction regressions: synthetic clocks and objects, no desktop input or windows."""
import copy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from app import DesktopPet
from engine import PetEngine
from interaction import InteractionState


class GameTests(unittest.TestCase):
    def test_game_credit_replaces_old_rest_context_once(self):
        engine = PetEngine()
        engine.decide()
        engine.action = "rest"
        before_rest = engine.brain.weights[0][:]
        self.assertTrue(engine.begin_game())
        expected = copy.deepcopy(engine.brain)
        expected.learn(engine.pending_features, "play", .9, source="intrinsic")
        for _ in range(7):
            engine.advance(1, allow_decisions=False)
        self.assertEqual(engine.action, "play")
        self.assertEqual(engine.brain.updates, 0)
        engine.finish_game(3)
        for actual_row, expected_row in zip(engine.brain.weights, expected.weights):
            for actual, reference in zip(actual_row, expected_row):
                self.assertAlmostEqual(actual, reference, places=14)
        self.assertEqual(engine.brain.weights[0], before_rest)
        count = engine.brain.updates
        self.assertIsNone(engine.finish_game(3))
        self.assertEqual(engine.brain.updates, count)

    def test_stationary_cursor_cannot_farm_game_catches(self):
        state = InteractionState()
        state.start_game()
        state.advance(.1, distance=100)
        self.assertEqual(state.advance(.1, distance=30), ["catch"])
        for _ in range(20):
            self.assertEqual(state.advance(.1, distance=30), [])
        self.assertEqual(state.catches, 1)
        for _ in range(2):
            state.advance(.1, distance=100)
            events = state.advance(.1, distance=30)
        self.assertEqual(events, ["catch", "finish"])
        self.assertFalse(state.playing)
        self.assertEqual(state.advance(1, distance=30), [])

    def test_game_timeout_and_paused_clock(self):
        state = InteractionState()
        state.start_game()
        state.advance(4)
        self.assertEqual(state.game_left, 8)
        state.advance(20, paused=True)
        self.assertEqual(state.game_left, 8)
        self.assertEqual(state.advance(8), ["finish"])
        self.assertEqual(state.advance(1), [])

    def test_frozen_or_cancelled_game_does_not_learn(self):
        for frozen, cancelled in ((True, False), (False, True)):
            engine = PetEngine()
            engine.settings["frozen"] = frozen
            engine.begin_game()
            before = engine.brain.to_dict()
            engine.finish_game(3, cancelled=cancelled)
            self.assertEqual(engine.brain.to_dict(), before)
            self.assertFalse(engine.memory[-1]["learned"])

    def test_game_save_stays_schema_compatible_and_does_not_replay(self):
        engine = PetEngine()
        old_keys = set(engine.to_dict())
        engine.begin_game()
        saved = engine.to_dict()
        self.assertEqual(set(saved), old_keys)
        restored = PetEngine.from_dict(saved)
        before = restored.brain.to_dict()
        self.assertIsNone(restored.finish_game(3))
        self.assertEqual(restored.brain.to_dict(), before)


class FakeClock:
    def __init__(self):
        self.now = 0
        self.jobs = {}
        self.counter = 0

    def after(self, milliseconds, callback):
        self.counter += 1
        self.jobs[self.counter] = (self.now + milliseconds, callback)
        return self.counter

    def after_cancel(self, token):
        self.jobs.pop(token, None)

    def advance(self, milliseconds):
        end = self.now + milliseconds
        while any(when <= end for when, _ in self.jobs.values()):
            token = min(self.jobs, key=lambda key: self.jobs[key][0])
            when, callback = self.jobs.pop(token)
            self.now = when
            callback()
        self.now = end


def stub_app():
    """Call real gesture methods with a pure clock; drawing and OS calls are replaced."""
    app = object.__new__(DesktopPet)
    app.engine = PetEngine()
    app.engine.decide()
    app.interaction = InteractionState()
    app.root = FakeClock()
    app.x = app.y = 300
    app.width = app.height = 208
    app.render_scale = 1.0
    app.area = (0, 0, 1920, 1040)
    app.click_delay = 530
    app.single_click = None
    app.double_release = False
    app.press_target = None
    app.dragging = False
    app.moved = False
    app.press_anchor = None
    app.panel = None
    app.draw = Mock()
    app.update_panel = Mock()
    app.save = Mock()
    app.root.geometry = Mock()
    app.open_menu = Mock()
    return app


def event(x=104, y=100):
    return SimpleNamespace(x=x, y=y, x_root=x + 300, y_root=y + 300)


class GestureTests(unittest.TestCase):
    def test_single_click_rewards_once_after_double_click_window(self):
        app = stub_app()
        app.press(event())
        app.release(event())
        self.assertEqual(app.engine.brain.user_updates, 0)
        app.root.advance(530)
        self.assertEqual(app.engine.brain.user_updates, 1)
        app.root.advance(1000)
        self.assertEqual(app.engine.brain.user_updates, 1)
        self.assertEqual(app.interaction.effect, "pet")

    def test_slow_double_click_starts_game_without_pet_reward_or_panel(self):
        app = stub_app()
        app.press(event())
        app.release(event())
        app.root.advance(400)
        app.double_click(event())
        app.release(event())
        app.root.advance(1000)
        self.assertTrue(app.interaction.playing)
        self.assertEqual(app.engine.brain.user_updates, 0)
        self.assertIsNone(app.panel)

    def test_feed_shortcut_is_immediate_and_only_once(self):
        app = stub_app()
        app.press(event(68, 190))
        app.release(event(68, 190))
        app.root.advance(1000)
        self.assertEqual(app.engine.brain.user_updates, 1)
        self.assertEqual(app.engine.memory[-1]["kind"], "feed")
        self.assertEqual(app.interaction.effect, "feed")

    def test_drag_cancels_pending_pet_and_game_without_rewards(self):
        app = stub_app()
        app.start_game()
        count = app.engine.brain.updates
        app.press(event())
        app.drag(event(135, 120))
        app.release(event(135, 120))
        app.root.advance(1000)
        self.assertFalse(app.interaction.playing)
        self.assertEqual(app.engine.brain.updates, count)
        self.assertEqual(app.interaction.effect, "drop")

    def test_pause_cancels_game_and_stale_finish_is_inert(self):
        app = stub_app()
        app.start_game()
        count = app.engine.brain.updates
        app.toggle("paused")
        self.assertFalse(app.interaction.playing)
        self.assertIsNone(app.engine.finish_game(3))
        self.assertEqual(app.engine.brain.updates, count)

    def test_toolbar_double_click_does_not_start_unrelated_game(self):
        app = stub_app()
        app.press(event(68, 190))
        app.release(event(68, 190))
        app.double_click(event(68, 190))
        app.release(event(68, 190))
        app.root.advance(1000)
        self.assertEqual(app.engine.brain.user_updates, 1)
        self.assertFalse(app.interaction.playing)

    def test_small_mini_medium_share_logical_hit_regions(self):
        app = stub_app()
        for scale in (.75, 1.0, 280 / 208):
            app.render_scale = scale
            self.assertEqual(app.quick_action_at(68 * scale, 190 * scale), "feed")
            self.assertIsNone(app.quick_action_at(104 * scale, 100 * scale))

    def test_external_feedback_cancels_pending_body_tap(self):
        app = stub_app()
        app.press(event())
        app.release(event())
        app.root.advance(100)
        app.interact("feed")
        app.start_game()
        before = copy.deepcopy(app.engine.brain.weights)
        app.root.advance(1000)
        self.assertEqual(app.engine.brain.user_updates, 1)
        self.assertEqual(app.engine.brain.weights, before)

    def test_delayed_single_click_rewards_action_at_click_time(self):
        app = stub_app()
        app.engine.action = "rest"
        context = app.engine.capture_feedback_context()
        expected = copy.deepcopy(app.engine.brain)
        expected.learn(context["features"], "rest", .8, source="user")
        app.press(event())
        app.release(event())
        app.engine.action = "wander"
        app.engine.pending_features = app.engine.features({"cursor_near": 1})
        app.root.advance(1000)
        self.assertEqual(app.engine.brain.weights, expected.weights)
        self.assertEqual(app.engine.memory[-1]["action"], "rest")


if __name__ == "__main__":
    unittest.main()
