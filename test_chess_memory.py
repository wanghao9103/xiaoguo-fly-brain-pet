import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from board_games import FEATURES, GamesSession
from chess_memory import ChessMemoryStore, MoveMemory, TOP_K


class MemoryTests(unittest.TestCase):
    def test_sparse_learning_and_exact_roundtrip(self):
        model = MoveMemory("gomoku", FEATURES["gomoku"])
        samples = [([0.] * 12, -.9), ([1.] * 12, .9)]
        self.assertEqual(len(model.encode(samples[0][0])), TOP_K)
        result = model.learn_batch(samples, rounds=20)
        self.assertLess(result["after"], result["before"] / 10)
        self.assertLess(model.predict(samples[0][0]), -.5)
        self.assertGreater(model.predict(samples[1][0]), .5)
        restored = MoveMemory.from_dict(json.loads(json.dumps(model.to_dict())), "gomoku", FEATURES["gomoku"])
        self.assertEqual(restored.to_dict(), model.to_dict())
        self.assertEqual(restored.predict([.4] * 12), model.predict([.4] * 12))

    def test_invalid_learning_does_not_partly_train(self):
        model = MoveMemory("gomoku", FEATURES["gomoku"])
        before = model.to_dict()
        for examples in ([], [([.5] * 12, float("nan"))],
                         [([.5] * 12, .9), ([2.] * 12, .9)],
                         [([True] * 12, .9)]):
            with self.assertRaises(ValueError):
                model.learn_batch(examples)
            self.assertEqual(model.to_dict(), before)
        bad = copy.deepcopy(before)
        bad["weights"][0] = float("inf")
        with self.assertRaises(ValueError):
            MoveMemory.from_dict(bad, "gomoku", FEATURES["gomoku"])

    def test_persistence_separation_lock_and_backup_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ChessMemoryStore(directory, FEATURES)
            xiangqi_before = store.models["xiangqi"].to_dict()
            store.models["gomoku"].learn_batch([([.5] * 12, .9)])
            expected = store.models["gomoku"].to_dict()
            store.save()
            with self.assertRaises(RuntimeError):
                ChessMemoryStore(directory, FEATURES)
            store.close()
            path = Path(directory) / "memory.json"
            path.write_text("broken", encoding="utf-8")
            restored = ChessMemoryStore(directory, FEATURES)
            self.assertIn("备份", restored.warning)
            self.assertEqual(restored.models["gomoku"].to_dict(), expected)
            self.assertEqual(restored.models["xiangqi"].to_dict(), xiangqi_before)
            restored.close()
            self.assertTrue(list(Path(directory).glob("*.damaged-*.json")))

    def test_both_corrupt_fail_closed_and_release_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memory.json"
            path.write_text("broken", encoding="utf-8")
            with self.assertRaises(ValueError):
                ChessMemoryStore(directory, FEATURES)
            self.assertEqual(path.read_text(encoding="utf-8"), "broken")
            with self.assertRaises(ValueError):  # validation error again, not a held lock
                ChessMemoryStore(directory, FEATURES)


if __name__ == "__main__":
    unittest.main()
