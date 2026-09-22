"""Mood rules are deterministic views; no desktop windows or real memory are used."""
import copy
import json
import unittest
from engine import PetEngine
from mood import ambient_message, select_mood, tear_phases
from app import DesktopPet
from test_interaction import stub_app


class MoodTests(unittest.TestCase):
    def setUp(self):
        self.engine = PetEngine()
        self.body = self.engine.body

    def test_idle_thresholds(self):
        for seconds, expected in ((44.9, "calm"), (45, "curious"), (119.9, "curious"),
                                  (120, "bored"), (299.9, "bored"), (300, "sleepy"),
                                  (599.9, "sleepy"), (600, "tearful")):
            self.body["idle"] = seconds
            self.assertEqual(select_mood(self.body).code, expected, seconds)

    def test_mood_is_read_only_and_does_not_add_saved_fields(self):
        self.body["idle"] = 150
        before = copy.deepcopy(self.engine.to_dict())
        for _ in range(100):
            select_mood(self.body)
            ambient_message(select_mood(self.body), self.body["idle"])
        self.assertEqual(self.engine.to_dict(), before)

    def test_touch_or_food_restores_short_lived_contentment(self):
        for kind in ("pet", "feed"):
            engine = PetEngine()
            engine.body["idle"] = 350
            self.assertEqual(select_mood(engine.body).code, "sleepy")
            engine.interact(kind)
            self.assertEqual(select_mood(engine.body).code, "content")
            engine.body["idle"] = 45
            self.assertEqual(select_mood(engine.body).code, "curious")

    def test_game_and_pause_take_priority(self):
        self.body["idle"] = 500
        self.assertEqual(select_mood(self.body, playing=True).code, "playful")
        self.assertEqual(select_mood(self.body, playing=True, paused=True).code, "paused")

    def test_low_energy_and_recovery(self):
        self.body["energy"] = .2
        self.assertEqual(select_mood(self.body).code, "sleepy")
        self.body["energy"] = .8
        self.assertEqual(select_mood(self.body).code, "calm")

    def test_pause_does_not_accumulate_neglect(self):
        self.body["idle"] = 40
        self.engine.settings["paused"] = True
        for _ in range(60):
            self.engine.advance(1)
        self.assertEqual(self.body["idle"], 40)
        self.engine.settings["paused"] = False
        for _ in range(5):
            self.engine.advance(1)
        self.assertEqual(select_mood(self.body).code, "curious")

    def test_restore_uses_saved_simulation_time_not_wall_clock(self):
        self.body["idle"] = 40
        restored = PetEngine.from_dict(json.loads(json.dumps(self.engine.to_dict())))
        self.assertEqual(restored.body["idle"], 40)
        self.assertEqual(select_mood(restored.body).code, "calm")
        for _ in range(5):
            restored.advance(1)
        self.assertEqual(select_mood(restored.body).code, "curious")

    def test_idle_bubbles_are_brief_and_spaced(self):
        self.body["idle"] = 120
        mood = select_mood(self.body)
        self.assertTrue(ambient_message(mood, 120))
        self.assertTrue(ambient_message(mood, 122.9))
        self.assertEqual(ambient_message(mood, 123), "")
        self.assertEqual(ambient_message(mood, 209.9), "")
        self.assertTrue(ambient_message(mood, 210))

    def test_render_commands_change_without_mutating_saved_state(self):
        class CanvasRecorder:
            def __init__(self):
                self.commands = []

            def delete(self, *args):
                self.commands = []

            def __getattr__(self, name):
                def record(*args, **kwargs):
                    self.commands.append((name, args, kwargs))
                return record

        app = stub_app()
        app.canvas = CanvasRecorder()
        app.hovered = False
        app.elapsed = 1.3
        app.greeting_until = app.feedback_until = 0
        app.feedback_message = ""
        app.previous_pointer = (1000, 1000)
        app.engine.action = "wander"
        poses = set()
        for idle in (0, 60, 180, 330, 650):
            app.engine.body["idle"] = idle
            before = copy.deepcopy(app.engine.to_dict())
            DesktopPet.draw(app)
            poses.add(repr(app.canvas.commands))
            self.assertEqual(app.engine.to_dict(), before)
        self.assertEqual(len(poses), 5)
        self.assertTrue(any(kwargs.get("tags") == "tear" for _, _, kwargs in app.canvas.commands))
        app.engine.interact("pet")
        DesktopPet.draw(app)
        self.assertFalse(any(kwargs.get("tags") == "tear" for _, _, kwargs in app.canvas.commands))

    def test_tear_bursts_continue_after_idle_reaches_its_cap(self):
        self.body["idle"] = 1200
        self.body["age_seconds"] = 1231
        self.assertEqual(len(tear_phases(self.body)), 2)
        self.body["age_seconds"] = 1240
        self.assertEqual(tear_phases(self.body), ())
        self.body["age_seconds"] = 1261
        self.assertEqual(len(tear_phases(self.body)), 2)
        self.assertEqual(self.body["idle"], 1200)

    def test_crying_yields_to_interaction_pause_and_energy_protection(self):
        self.body["idle"] = 700
        self.assertEqual(select_mood(self.body).code, "tearful")
        self.assertEqual(select_mood(self.body, paused=True).code, "paused")
        self.assertEqual(select_mood(self.body, playing=True).code, "playful")
        self.body["energy"] = .01
        self.assertEqual(select_mood(self.body).code, "sleepy")
        self.assertFalse(tear_phases(self.body))
        self.body["energy"] = .8
        self.engine.interact("feed")
        self.assertEqual(select_mood(self.body).code, "content")
        self.assertFalse(tear_phases(self.body))


if __name__ == "__main__":
    unittest.main()
