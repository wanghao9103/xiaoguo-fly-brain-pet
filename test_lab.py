"""Lab isolation and localhost API tests. Uses synthetic models, never pet save files."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from brain import FlyBrain
from lab import LabService, LabSession


class SessionTests(unittest.TestCase):
    def test_manual_feedback_and_context_do_not_change_original_pet(self):
        original = FlyBrain(seed=7)
        state = original.to_dict()
        lab = LabSession(state)
        lab.command("reset", {"source": "pet", "seed": 42})
        before = lab.state()["probabilities"]["play"]
        lab.command("train", {"action": "play", "reward": 1, "steps": 20})
        self.assertGreater(lab.state()["probabilities"]["play"], before)
        self.assertEqual(lab.local_updates, 20)
        self.assertEqual(original.to_dict(), state)
        self.assertEqual(lab.pet_snapshot, state)

    def test_bad_commands_do_not_mutate_model(self):
        lab = LabSession()
        before = lab.brain.to_dict()
        for name, payload in (
            ("train", {"action": "play", "reward": 1, "steps": True}),
            ("train", {"action": "play", "reward": 1, "steps": 201}),
            ("train", {"action": "play", "reward": float("nan"), "steps": 1}),
            ("train", {"action": "teleport", "reward": 1, "steps": 1}),
            ("context", {"values": [0] * 11}),
            ("reset", {"source": "pet"}),
        ):
            with self.assertRaises((ValueError, TypeError)):
                lab.command(name, payload)
            self.assertEqual(lab.brain.to_dict(), before)

    def test_inspection_and_context_changes_do_not_train_or_sample(self):
        lab = LabSession()
        before = lab.brain.to_dict()
        for _ in range(10):
            lab.state()
        lab.command("context", {"values": [.5] * 12})
        self.assertEqual(lab.brain.to_dict(), before)
        self.assertEqual(lab.local_updates, 0)

    def test_sampling_changes_only_experiment_rng(self):
        lab = LabSession()
        weights = copy.deepcopy(lab.brain.weights)
        result = lab.command("sample", {"count": 100})
        self.assertEqual(sum(result["sample"].values()), 100)
        self.assertEqual(lab.brain.weights, weights)
        self.assertEqual(lab.local_updates, 0)

    def test_automatic_experiment_leaves_manual_model_unchanged(self):
        lab = LabSession()
        lab.command("train", {"action": "play", "reward": 1, "steps": 3})
        before = lab.brain.to_dict()
        result = lab.command("experiment", {"id": "association", "seed": 42})
        self.assertEqual(lab.brain.to_dict(), before)
        self.assertEqual(lab.local_updates, 3)
        self.assertEqual(result["experiment"]["id"], "association")
        json.dumps(lab.export(), allow_nan=False)

    def test_report_keeps_immutable_experiment_origin_after_further_training(self):
        lab = LabSession()
        lab.command("experiment", {"id": "association", "seed": 42})
        before = copy.deepcopy(lab.export()["experiment_start"])
        self.assertTrue(lab.state()["experiment_matches_current"])
        lab.command("train", {"action": "play", "reward": 1, "steps": 20})
        report = lab.export()
        self.assertFalse(lab.state()["experiment_matches_current"])
        self.assertEqual(report["experiment_start"], before)
        self.assertEqual(report["experiment_start"]["manual_updates"], 0)
        self.assertEqual(report["current_manual_state"]["local_updates"], 20)


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report_directory = tempfile.TemporaryDirectory()
        cls.service = LabService(report_dir=cls.report_directory.name).start()

    @classmethod
    def tearDownClass(cls):
        cls.service.stop()
        cls.report_directory.cleanup()

    def request(self, route, data=None, token=True, origin=None, host=None):
        headers = {"X-Lab-Token": self.service.token} if token else {}
        if origin:
            headers["Origin"] = origin
        if host:
            headers["Host"] = host
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = Request(self.service.url.rstrip("/") + route, headers=headers,
                          data=None if data is None else json.dumps(data).encode())
        return urlopen(request, timeout=20)

    def test_real_http_page_state_training_and_export(self):
        with self.request("/") as response:
            page = response.read().decode()
        self.assertIn("神经网络实验室", page)
        self.assertNotIn("__BOOT__", page)
        with self.request("/api/reset", {"source": "fresh", "seed": 42}) as response:
            self.assertEqual(json.load(response)["state"]["local_updates"], 0)
        with self.request("/api/train", {"action": "rest", "reward": 1, "steps": 1}) as response:
            data = json.load(response)
        self.assertEqual(data["state"]["local_updates"], 1)
        self.assertGreater(data["state"]["probabilities"]["rest"], .25)
        with self.request("/api/export") as response:
            self.assertEqual(json.load(response)["schema_version"], 1)

    def test_missing_token_foreign_origin_or_host_are_rejected(self):
        for kwargs in ({"token": False}, {"origin": "https://example.com"}, {"host": "example.com"}):
            with self.assertRaises(HTTPError) as error:
                self.request("/api/state", **kwargs)
            self.assertEqual(error.exception.code, 403)
            error.exception.close()

    def test_save_report_creates_valid_file_in_service_owned_directory(self):
        with self.request("/api/export-report", {}) as response:
            path = Path(json.load(response)["saved_to"])
        self.assertEqual(path.parent, Path(self.report_directory.name).resolve())
        report = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(report["schema_version"], 1)
        self.assertIn("current_manual_state", report)
        self.assertIn("experiment_start", report)

    def test_invalid_commands_and_file_paths_are_rejected(self):
        with self.assertRaises(HTTPError) as error:
            self.request("/api/train", {"action": "rest", "reward": 1, "steps": 0})
        self.assertEqual(error.exception.code, 400)
        error.exception.close()
        with self.assertRaises(HTTPError) as error:
            self.request("/brain.py")
        self.assertEqual(error.exception.code, 404)
        error.exception.close()


if __name__ == "__main__":
    unittest.main()
