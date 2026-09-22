import json
import unittest

from gomoku import FEATURE_LABELS, GomokuGame


class GomokuTests(unittest.TestCase):
    def test_initial_and_empty_center(self):
        game = GomokuGame()
        self.assertEqual(len(game.legal_moves()), 225)
        self.assertEqual(game.turn, 1)
        self.assertIsNone(game.winner)
        self.assertEqual(game.rank_moves()[0]["move"], [7, 7])

    def test_four_directions_win(self):
        for dr, dc in ((0, 1), (1, 0), (1, 1), (1, -1)):
            with self.subTest(direction=(dr, dc)):
                game = GomokuGame()
                for k in range(4):
                    game.board[7 + k * dr][7 + k * dc] = 1
                game.play([7 + 4 * dr, 7 + 4 * dc])
                self.assertEqual(game.winner, 1)
                self.assertEqual(len(game.winning_line), 5)
                self.assertEqual(game.legal_moves(), [])

    def test_long_line_and_white_win(self):
        game = GomokuGame()
        game.turn = -1
        for col in (3, 4, 5, 7, 8):
            game.board[7][col] = -1
        game.play([7, 6])
        self.assertEqual(game.winner, -1)
        self.assertEqual(len(game.winning_line), 6)

    def test_validation_is_atomic(self):
        game = GomokuGame()
        game.play([7, 7])
        before = game.snapshot()
        invalid = (None, [], [1], [1, 2, 3], "77", [True, 1], [1, False],
                   [1.0, 1], [-1, 3], [15, 3], [7, 7])
        for move in invalid:
            with self.subTest(move=move), self.assertRaises(ValueError):
                game.play(move)
            self.assertEqual(game.snapshot(), before)

    def test_termination_and_undo(self):
        game = GomokuGame()
        for col in range(4):
            game.play([7, col])
            game.play([9, col])
        game.play([7, 4])
        self.assertEqual(game.winner, 1)
        with self.assertRaises(ValueError):
            game.play([0, 0])
        self.assertEqual(game.rank_moves(), [])
        game.undo(1)
        self.assertIsNone(game.winner)
        self.assertEqual(game.turn, 1)
        self.assertEqual(game.winning_line, [])
        game.play([7, 4])
        self.assertEqual(game.winner, 1)
        game.undo(99)
        self.assertEqual(game.snapshot(), GomokuGame().snapshot())

    def test_default_two_ply_undo_and_invalid_count(self):
        game = GomokuGame()
        game.play([7, 7])
        game.play([7, 8])
        game.play([8, 8])
        game.undo()
        self.assertEqual(len(game.history), 1)
        self.assertEqual(game.turn, -1)
        for count in (0, -1, True, 1.5):
            with self.assertRaises(ValueError):
                game.undo(count)

    def test_immediate_win_over_defense(self):
        game = GomokuGame()
        for col in range(4):
            game.board[4][col] = 1
            game.board[9][col] = -1
        ranked = game.rank_moves()
        self.assertEqual([entry["move"] for entry in ranked], [[4, 4]])
        self.assertTrue(all(entry["forced"] for entry in ranked))

    def test_blocks_only_available_winning_point(self):
        for side in (1, -1):
            with self.subTest(side=side):
                game = GomokuGame()
                game.turn = side
                for col in range(4):
                    game.board[5][col] = -side
                ranked = game.rank_moves()
                self.assertEqual([entry["move"] for entry in ranked], [[5, 4]])
                self.assertTrue(ranked[0]["forced"])

    def test_open_four_has_two_winning_options(self):
        game = GomokuGame()
        for col in range(4, 8):
            game.board[6][col] = 1
        ranked = game.rank_moves()
        self.assertEqual({tuple(item["move"]) for item in ranked}, {(6, 3), (6, 8)})
        self.assertTrue(all(item["forced"] for item in ranked))

    def test_broken_four_is_detected(self):
        game = GomokuGame()
        for col in (4, 5, 7, 8):
            game.board[6][col] = -1
        self.assertEqual(game.rank_moves()[0]["move"], [6, 6])
        self.assertTrue(game.rank_moves()[0]["forced"])

    def test_rank_features_do_not_mutate_and_clone_is_independent(self):
        game = GomokuGame()
        for move in ([7, 7], [6, 7], [7, 8], [6, 8], [8, 6], [5, 9]):
            game.play(move)
        before = game.snapshot()
        ranked = game.rank_moves(limit=8)
        self.assertEqual(len(ranked), 8)
        self.assertEqual([item["score"] for item in ranked], sorted((item["score"] for item in ranked), reverse=True))
        self.assertTrue(all(not item["forced"] for item in ranked))
        for item in ranked:
            features = game.move_features(item["move"])
            self.assertEqual(len(features), len(FEATURE_LABELS))
            self.assertEqual(len(features), 12)
            self.assertTrue(all(type(value) is float and 0 <= value <= 1 for value in features))
        self.assertEqual(game.snapshot(), before)
        clone = game.clone()
        clone.play(ranked[0]["move"])
        self.assertEqual(game.snapshot(), before)
        decoded = json.loads(json.dumps(game.snapshot()))
        self.assertEqual(decoded, game.snapshot())
        decoded["board"][0][0] = 99
        decoded["history"][0]["move"][0] = 99
        self.assertEqual(game.snapshot(), before)

    def test_features_are_board_geometry_not_search(self):
        game = GomokuGame()
        game.rank_moves = lambda *args, **kwargs: self.fail("Features must not call search")
        features = game.move_features([7, 7])
        self.assertEqual(features[8], 1.0)
        self.assertEqual(features[9], 0.0)

    def test_full_board_draw(self):
        game = GomokuGame()
        # Alternating pairs per row prevent length-five lines in all directions.
        game.board = [[1 if (r + c // 2) % 2 == 0 else -1 for c in range(15)] for r in range(15)]
        game.turn = game.board[14][14]
        game.board[14][14] = 0
        game.play([14, 14])
        self.assertEqual(game.winner, 0)
        self.assertEqual(game.winning_line, [])


if __name__ == "__main__":
    unittest.main()
