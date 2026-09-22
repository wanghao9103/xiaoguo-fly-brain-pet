"""Isolated experiment contracts; never creates a pet, GUI, or a save directory."""
import copy
import json
import math
import random
import unittest
from unittest.mock import patch

from brain import FlyBrain
from experiments import (BASE_FEATURE_LABELS, EXPERIMENTS, PRESETS,
                         perturb_features, run_experiment, to_features)


class ExperimentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = {kind: run_experiment(kind, seed=42) for kind in EXPERIMENTS}

    def test_presets_and_feature_validation(self):
        self.assertEqual(len(BASE_FEATURE_LABELS), 12)
        self.assertEqual(set(PRESETS), {"tired", "lively", "social"})
        for base in PRESETS.values():
            features = to_features(base)
            self.assertEqual(len(features), 24)
            for i, original in enumerate(base):
                self.assertEqual(features[2 * i], original)
                self.assertEqual(features[2 * i] + features[2 * i + 1], 1)
        bad = [None, "0" * 12, [0] * 11, [0] * 13, {str(i): 0 for i in range(12)}]
        for value in (True, "0", -.1, 1.1, float("nan"), float("inf"), 10**1000):
            bad.append([value] + [.5] * 11)
        for value in bad:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    to_features(value)

    def test_noise_helper_rebuilds_complements_and_is_reproducible(self):
        left, right = random.Random(73), random.Random(73)
        for amplitude in (0, .02, .08, .15, 1):
            for base in (PRESETS["tired"], PRESETS["lively"], [0, 1] * 6):
                probe = perturb_features(base, amplitude, left)
                self.assertEqual(probe, perturb_features(base, amplitude, right))
                self.assertTrue(all(0 <= value <= 1 for value in probe))
                for i in range(12):
                    self.assertEqual(probe[2 * i] + probe[2 * i + 1], 1)
                    self.assertLessEqual(abs(probe[2 * i] - base[i]), amplitude + 1e-15)
        for amplitude in (-.1, 1.1, True, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                perturb_features(PRESETS["tired"], amplitude, random.Random(1))

    def test_repeat_seed_is_identical_except_elapsed(self):
        for kind, first in self.results.items():
            repeated = run_experiment(kind, seed=42)
            first = copy.deepcopy(first)
            first.pop("elapsed_seconds")
            repeated.pop("elapsed_seconds")
            with self.subTest(kind=kind):
                self.assertEqual(first, repeated)

    def test_caller_model_and_saved_rng_are_untouched(self):
        caller = FlyBrain(seed=11, width=96, fan_in=4, k=12)
        features = to_features(PRESETS["social"])
        caller.learn(features, "approach", .8, source="user")
        caller.choose(features)
        initial = caller.to_dict()
        exact_before = json.dumps(initial, allow_nan=False, sort_keys=True)
        reference = FlyBrain.from_dict(initial)
        for kind in EXPERIMENTS:
            run_experiment(kind, seed=19, initial=initial)
            self.assertEqual(json.dumps(initial, allow_nan=False, sort_keys=True), exact_before)
            self.assertEqual(caller.to_dict(), initial)
        self.assertEqual([caller.choose(features) for _ in range(20)],
                         [reference.choose(features) for _ in range(20)])

    def test_experiments_never_sample_actions(self):
        with patch.object(FlyBrain, "choose", side_effect=AssertionError("must not consume action RNG")):
            run_experiment("noise", seed=2, initial=FlyBrain(width=32, k=8).to_dict())

    def test_interference_equal_training_budget_and_frozen_has_no_updates(self):
        result = self.results["interference"]
        new_only, rehearsal, frozen = result["table"]["rows"]
        self.assertEqual(new_only["updates"], rehearsal["updates"])
        self.assertEqual(new_only["updates"], 256)
        self.assertEqual(new_only["a_updates"], 0)
        self.assertEqual(new_only["b_updates"], 256)
        self.assertEqual(rehearsal["a_updates"], 128)
        self.assertEqual(rehearsal["b_updates"], 128)
        self.assertEqual(frozen["updates"], 0)
        self.assertEqual(frozen["a_updates"], 0)
        self.assertEqual(frozen["b_updates"], 0)
        self.assertEqual(frozen["a_change"], 0)
        for series in result["chart"]["series"]:
            if series["name"].startswith("冻结旧模型"):
                self.assertTrue(all(point[1] == series["points"][0][1] for point in series["points"]))

    def test_noise_frozen_probabilities_do_not_mislabel_tie_accuracy(self):
        for row in self.results["noise"]["table"]["rows"]:
            self.assertEqual(row["samples"], 60)
            self.assertEqual(row["frozen_probability"], .25)
            self.assertEqual(row["frozen_greedy"], .5)
        self.assertTrue(any("不是实际随机抽样" in note for note in self.results["noise"]["notes"]))

    def test_association_reversal_and_sensitivity_include_control_values(self):
        association = self.results["association"]["table"]["rows"]
        self.assertEqual(association[0]["updates"], 0)
        self.assertEqual(association[0]["tired_rest"], .25)
        self.assertEqual(association[-1]["updates"], 384)
        reversal = self.results["reversal"]["table"]["rows"]
        self.assertEqual(reversal[0]["updates"], 0)
        self.assertEqual(reversal[-1]["updates"], 160)
        sensitivity = self.results["sensitivity"]
        reference = sensitivity["metrics"][0]["value"]
        self.assertEqual(len(sensitivity["table"]["rows"]), 12)
        for row in sensitivity["table"]["rows"]:
            self.assertAlmostEqual(row["minus_delta"], row["minus_probability"] - reference)
            self.assertAlmostEqual(row["plus_delta"], row["plus_probability"] - reference)
            self.assertGreaterEqual(row["minus_changes"], 0)
            self.assertGreaterEqual(row["plus_changes"], 0)

    def test_fixed_schema_json_only_and_all_numbers_finite(self):
        fields = {"id", "title", "description", "summary", "metrics", "chart", "table", "notes", "elapsed_seconds"}

        def visit(value):
            if isinstance(value, dict):
                self.assertTrue(all(isinstance(key, str) for key in value))
                for nested in value.values():
                    visit(nested)
            elif isinstance(value, list):
                for nested in value:
                    visit(nested)
            elif isinstance(value, (int, float)):
                self.assertTrue(math.isfinite(value))
            else:
                self.assertIsInstance(value, str)

        for kind, result in self.results.items():
            with self.subTest(kind=kind):
                self.assertEqual(set(result), fields)
                self.assertEqual(result["id"], kind)
                self.assertEqual(json.loads(json.dumps(result, allow_nan=False)), result)
                self.assertGreaterEqual(result["elapsed_seconds"], 0)
                visit(result)
                for metric in result["metrics"]:
                    self.assertIn(metric["format"], ("percent", "number", "pp"))
                for series in result["chart"]["series"]:
                    for x, y in series["points"]:
                        self.assertGreaterEqual(x, 0)
                        self.assertTrue(0 <= y <= 1)
                for column in result["table"]["columns"]:
                    self.assertIn(column["format"], ("percent", "number", "pp", "text"))
                    self.assertTrue(all(column["key"] in row for row in result["table"]["rows"]))

    def test_invalid_kind_seed_and_initial_are_rejected(self):
        for kind in (None, [], {}, "unknown"):
            with self.assertRaises(ValueError):
                run_experiment(kind)
        for seed in (True, 1.0, "42", None, 2**63):
            with self.assertRaises(ValueError):
                run_experiment("noise", seed=seed)
        for initial in ({}, [], {"schema": 999}):
            with self.assertRaises(ValueError):
                run_experiment("association", initial=initial)


if __name__ == "__main__":
    unittest.main()
