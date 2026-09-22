"""Learning and data-boundary tests; all synthetic, offline, standard-library only."""

import copy
import json
import math
import unittest

from brain import ACTIONS, FEATURE_NAMES, FlyBrain
from verify_learning import context, run_verification


class FlyBrainTests(unittest.TestCase):
    def setUp(self):
        self.brain = FlyBrain()
        self.features = context(.8, .6, .4, .9, .7, .3, .2, .1, .5, .6, .8, .4)

    def test_sparse_nonnegative_unit_norm_and_zero_input(self):
        encoded = self.brain.encode(self.features)
        self.assertEqual(len(encoded), self.brain.width)
        self.assertLessEqual(sum(value > 0 for value in encoded), self.brain.k)
        self.assertTrue(all(value >= 0 for value in encoded))
        self.assertAlmostEqual(sum(value * value for value in encoded), 1)
        self.assertEqual(self.brain.encode([0] * len(FEATURE_NAMES)), [0] * self.brain.width)

    def test_ties_choose_lower_indices(self):
        self.brain.connection_weights = [[1 / self.brain.fan_in] * self.brain.fan_in
                                         for _ in range(self.brain.width)]
        encoded = self.brain.encode([1] * len(FEATURE_NAMES))
        self.assertEqual([i for i, value in enumerate(encoded) if value > 0], list(range(self.brain.k)))

    def test_positive_negative_rewards_and_only_selected_row_changes(self):
        before = self.brain.probabilities(self.features)[2]
        rows_before = copy.deepcopy(self.brain.weights)
        connections_before = copy.deepcopy(self.brain.connections)
        projection_before = copy.deepcopy(self.brain.connection_weights)
        result = self.brain.learn(self.features, "approach", 1, source="user")
        after_positive = self.brain.probabilities(self.features)[2]
        self.assertGreater(after_positive, before)
        self.assertGreater(result["error"], 0)
        self.assertGreater(result["weight_change"], 0)
        for i in (0, 1, 3):
            self.assertEqual(self.brain.weights[i], rows_before[i])
        self.brain.learn(self.features, "approach", -1)
        self.assertLess(self.brain.probabilities(self.features)[2], after_positive)
        self.assertEqual(self.brain.connections, connections_before)
        self.assertEqual(self.brain.connection_weights, projection_before)
        self.assertEqual((self.brain.updates, self.brain.user_updates), (2, 1))

    def test_context_learning_reversal_and_persistence_evidence(self):
        result = run_verification()
        self.assertTrue(result["passed"], result["checks"])

    def test_json_round_trip_scores_rng_and_detached_arrays(self):
        for _ in range(20):
            self.brain.learn(self.features, "play", .7)
        for _ in range(7):
            self.brain.choose(self.features)
        state = self.brain.to_dict()
        restored = FlyBrain.from_dict(json.loads(json.dumps(state, allow_nan=False)))
        self.assertEqual(self.brain.scores(self.features), restored.scores(self.features))
        self.assertEqual(self.brain.probabilities(self.features), restored.probabilities(self.features))
        self.assertEqual([self.brain.choose(self.features) for _ in range(50)],
                         [restored.choose(self.features) for _ in range(50)])
        state["weights"][0][0] = 1.0
        self.assertEqual(self.brain.weights[0][0], 0)
        self.assertEqual(restored.weights[0][0], 0)

    def test_stable_softmax_exploration_and_bounded_updates(self):
        for _ in range(1000):
            self.brain.learn(self.features, "rest", 1)
        probs = self.brain.probabilities(self.features)
        self.assertAlmostEqual(sum(probs), 1)
        self.assertTrue(all(p >= self.brain.exploration / len(ACTIONS) for p in probs))
        self.assertTrue(all(math.isfinite(w) and abs(w) <= self.brain.weight_limit
                            for row in self.brain.weights for w in row))

    def test_reject_invalid_features_and_rewards_before_mutation(self):
        invalid_features = [[0] * 23, [0] * 25, "0" * 24, None]
        for value in (float("nan"), float("inf"), float("-inf"), -.1, 1.1, True, "0"):
            invalid_features.append([value] + self.features[1:])
        for features in invalid_features:
            with self.subTest(features=features):
                with self.assertRaises(ValueError):
                    self.brain.encode(features)
        for reward in (float("nan"), float("inf"), -1.1, 1.1, True, None, "1"):
            with self.subTest(reward=reward):
                with self.assertRaises(ValueError):
                    self.brain.learn(self.features, "rest", reward)
        with self.assertRaises(ValueError):
            self.brain.learn(self.features, "teleport", 1)
        with self.assertRaises(ValueError):
            self.brain.learn(self.features, "rest", 1, source="unknown")
        self.assertEqual(self.brain.updates, 0)

    def test_reject_invalid_saved_state(self):
        cases = []

        def changed(path, value):
            state = self.brain.to_dict()
            current = state
            for key in path[:-1]:
                current = current[key]
            current[path[-1]] = value
            cases.append((str(path), state))

        changed(["schema"], 2)
        changed(["schema"], True)
        changed(["kind"], "other")
        changed(["feature_names"], list(reversed(FEATURE_NAMES)))
        changed(["config", "width"], 0)
        changed(["config", "width"], 8193)
        changed(["config", "k"], 385)
        changed(["config", "fan_in"], 25)
        changed(["config", "temperature"], 0)
        changed(["config", "learning_rate"], float("nan"))
        changed(["connections", 0, 0], 24)
        changed(["connections", 0, 0], -1)
        changed(["connections", 0, 0], True)
        changed(["connections", 0], [0] * self.brain.fan_in)
        changed(["connections", 0], [0])
        changed(["connection_weights", 0, 0], float("inf"))
        changed(["connection_weights", 0, 0], -1)
        changed(["weights", 0, 0], float("nan"))
        changed(["weights", 0, 0], 100)
        changed(["weights", 0], [0])
        changed(["updates"], -1)
        changed(["user_updates"], 1)
        changed(["rng_state", 0], 2)
        changed(["rng_state", 1, 0], -1)
        changed(["rng_state", 1, 624], 625)
        changed(["rng_state", 2], float("nan"))
        cases.extend([("empty", {}), ("null", None), ("array", [])])
        for label, state in cases:
            with self.subTest(case=label):
                with self.assertRaises(ValueError):
                    FlyBrain.from_dict(state)


if __name__ == "__main__":
    unittest.main()
