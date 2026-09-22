"""Decision evidence must be faithful and must not affect action selection."""
import copy
import unittest
from engine import PetEngine


class DecisionEvidenceTests(unittest.TestCase):
    def test_snapshot_matches_actual_choice_and_its_probabilities(self):
        engine = PetEngine()
        features = engine.features({"cursor_near": .9})
        clone = copy.deepcopy(engine.brain)
        probabilities = clone.probabilities(features)
        expected = clone.choose(features)
        chosen = engine.decide({"cursor_near": .9})
        self.assertEqual(chosen, expected)
        self.assertEqual(engine.last_decision["action"], chosen)
        self.assertEqual(list(engine.last_decision["probabilities"].values()), probabilities)
        self.assertEqual(engine.brain.rng.getstate(), clone.rng.getstate())
        before = copy.deepcopy(engine.last_decision)
        engine.interact("feed")
        self.assertEqual(engine.last_decision, before)

    def test_reading_evidence_never_changes_rng_or_weights(self):
        first, second = PetEngine(), PetEngine()
        first.decide()
        second.decide()
        for _ in range(50):
            first.describe_decision(compact=True)
        self.assertEqual(first.brain.to_dict(), second.brain.to_dict())
        self.assertEqual([first.decide() for _ in range(20)], [second.decide() for _ in range(20)])

    def test_protection_and_user_commands_have_distinct_sources(self):
        engine = PetEngine()
        original_rng = engine.brain.rng.getstate()
        engine.body["energy"] = .01
        self.assertEqual(engine.decide(), "rest")
        self.assertEqual(engine.last_decision["source"], "protection")
        self.assertEqual(engine.brain.rng.getstate(), original_rng)
        engine.body["energy"] = .8
        self.assertTrue(engine.begin_game())
        self.assertEqual(engine.last_decision["source"], "interaction")
        self.assertIsNone(engine.last_decision["probabilities"])
        self.assertEqual(engine.brain.rng.getstate(), original_rng)
        before = copy.deepcopy(engine.last_decision)
        engine.settings["paused"] = True
        self.assertFalse(engine.begin_game())
        self.assertEqual(engine.last_decision, before)

    def test_snapshot_is_transient_and_compatible_with_saved_state(self):
        engine = PetEngine()
        engine.decide()
        self.assertNotIn("last_decision", engine.to_dict())
        loaded = PetEngine.from_dict(engine.to_dict())
        self.assertIsNone(loaded.last_decision)
        self.assertEqual(loaded.brain.to_dict(), engine.brain.to_dict())


if __name__ == "__main__":
    unittest.main()
