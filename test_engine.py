"""Integration checks use temporary directories; no real pet memory is touched."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from engine import PetEngine
from storage import InstanceLock, PetStore
from app import clamp_position


class EngineTests(unittest.TestCase):
    def test_feedback_credits_decision_context_before_feeding(self):
        engine = PetEngine()
        engine.decide({"cursor_near": .8})
        expected = copy.deepcopy(engine.brain)
        features = engine.pending_features[:]
        expected.learn(features, engine.action, .6, source="user")
        engine.interact("feed")
        self.assertEqual(engine.brain.weights, expected.weights)
        self.assertNotEqual(engine.features(), features)
        self.assertTrue(engine.memory[-1]["learned"])

    def test_pause_and_freeze_do_not_update_weights(self):
        engine = PetEngine()
        engine.decide()
        engine.settings["frozen"] = True
        before = engine.brain.to_dict()["weights"]
        for _ in range(20):
            engine.advance(1)
        engine.interact("praise")
        self.assertEqual(engine.brain.weights, before)
        self.assertEqual(engine.brain.updates, 0)
        engine.settings["paused"] = True
        body = dict(engine.body)
        for _ in range(20):
            engine.advance(1)
        self.assertEqual(body, engine.body)
        engine.interact("pet")
        self.assertEqual(engine.brain.updates, 0)

    def test_autonomous_action_clock_and_body_bounds(self):
        engine = PetEngine()
        for _ in range(120):
            engine.advance(1, {"cursor_near": .6})
        self.assertEqual(engine.brain.updates, 20)
        for key in ("energy", "satiety", "social", "curiosity", "recent_touch", "recent_food"):
            self.assertTrue(0 <= engine.body[key] <= 1)

    def test_complete_json_round_trip(self):
        engine = PetEngine()
        engine.start_session()
        engine.decide({"cursor_near": .6})
        engine.advance(1)
        engine.interact("pet")
        engine.position = [220, 330]
        restored = PetEngine.from_dict(json.loads(json.dumps(engine.to_dict())))
        self.assertEqual(engine.to_dict(), restored.to_dict())
        for _ in range(12):
            self.assertEqual(engine.brain.choose(engine.features()), restored.brain.choose(engine.features()))

    def test_bad_business_state_is_rejected(self):
        for field, value in (("schema_version", True), ("schema_version", 1.0),
                             ("decision_elapsed", True), ("extra", float("nan")),
                             ("sessions", -2), ("position", [1e50, 0])):
            data = PetEngine().to_dict()
            data[field] = value
            with self.assertRaises(ValueError, msg=field):
                PetEngine.from_dict(data)

    def test_position_stays_on_work_area(self):
        self.assertEqual(clamp_position(-100, 900, (0, 0, 1920, 1040)), (0, 832))
        self.assertEqual(clamp_position(20, 20, (0, 0, 100, 100)), (0, 0))

    def test_invalid_memory_timestamp_and_boolean_reward(self):
        engine = PetEngine()
        engine.interact("pet")
        for field, value in (("at", "not a date"), ("at", "2026-09-22T12:00:00"), ("reward", True)):
            data = copy.deepcopy(engine.to_dict())
            data["memory"][0][field] = value
            with self.assertRaises(ValueError):
                PetEngine.from_dict(data)


class StorageTests(unittest.TestCase):
    def test_previous_generation_and_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            store = PetStore(directory)
            engine = PetEngine()
            store.save(engine)
            first = engine.to_dict()
            engine.start_session()
            store.save(engine)
            self.assertEqual(store.read(store.backup).to_dict(), first)
            store.path.write_text("{broken", encoding="utf-8")
            recovered, warning = store.load()
            self.assertTrue(warning)
            self.assertEqual(recovered.to_dict(), first)
            store.save(recovered)
            self.assertEqual(len(list(Path(directory).glob("memory.damaged-*.json"))), 1)

    def test_corrupt_backup_is_preserved_across_later_saves(self):
        with tempfile.TemporaryDirectory() as directory:
            store = PetStore(directory)
            store.backup.write_text("keep this damaged backup", encoding="utf-8")
            engine, warning = store.load()
            self.assertTrue(warning)
            store.save(engine)
            store.save(engine)
            archives = list(Path(directory).glob("memory.damaged-backup-*.json"))
            self.assertEqual(len(archives), 1)
            self.assertEqual(archives[0].read_text(), "keep this damaged backup")

    def test_deeply_corrupt_json_recovers_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            store = PetStore(directory)
            engine = PetEngine()
            store.save(engine)
            store.save(engine)
            store.path.write_text("[" * 5000 + "]" * 5000, encoding="utf-8")
            recovered, warning = store.load()
            self.assertTrue(warning)
            self.assertEqual(recovered.to_dict(), engine.to_dict())

    def test_replace_failure_keeps_old_primary_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as directory:
            store = PetStore(directory)
            engine = PetEngine()
            store.save(engine)
            original = store.path.read_bytes()
            engine.start_session()
            with patch("storage.os.replace", side_effect=PermissionError("injected")):
                with self.assertRaises(PermissionError):
                    store.save(engine)
            self.assertEqual(store.path.read_bytes(), original)
            self.assertFalse(list(Path(directory).glob(".writing-*.tmp")))

    def test_second_instance_cannot_write_same_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second = InstanceLock(directory), InstanceLock(directory)
            first.acquire()
            try:
                with self.assertRaises(RuntimeError):
                    second.acquire()
            finally:
                first.release()
            second.acquire()
            second.release()


if __name__ == "__main__":
    unittest.main()
