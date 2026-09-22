import math
import unittest

from xiangqi import FEATURE_LABELS, XiangqiGame


def position(pieces, turn=1):
    board = [["."] * 9 for _ in range(10)]
    for piece, row, col in pieces:
        board[row][col] = piece
    return XiangqiGame(board, turn)


KINGS = [("K", 9, 4), ("k", 0, 3)]


class XiangqiRulesTests(unittest.TestCase):
    def test_initial_board_and_moves(self):
        game = XiangqiGame()
        self.assertEqual(sum(cell != "." for row in game.board for cell in row), 32)
        self.assertEqual(len(game.legal_moves()), 44)
        self.assertEqual(game.turn, 1)
        self.assertIsNone(game.winner)
        self.assertFalse(game.snapshot()["check"])

    def test_strict_inputs_do_not_mutate(self):
        game = XiangqiGame()
        before = game.snapshot()
        for move in (None, [], [6, 0], [6, 0, 5, 0, 1], [True, 0, 5, 0],
                     [6.0, 0, 5, 0], [6, 0, 10, 0], [-1, 0, 0, 0],
                     [0, 0, 1, 0], [6, 0, 6, 1], [6, 0, 6, 0]):
            with self.subTest(move=move), self.assertRaises(ValueError):
                game.play(move)
            self.assertEqual(game.snapshot(), before)
        for count in (True, 0, -1, 1.5):
            with self.assertRaises(ValueError):
                game.undo(count)

    def test_custom_board_validation(self):
        for board in ([], ["........."] * 9, ["........"] * 10,
                      ["........."] * 10, ["xxxxxxxxx"] * 10):
            with self.assertRaises(ValueError):
                XiangqiGame(board)
        for side in (True, 0, 2, "1"):
            with self.assertRaises(ValueError):
                XiangqiGame(turn=side)

    def test_horse_leg_both_sides_and_axes(self):
        for blocker in ("P", "p"):
            game = position(KINGS + [("N", 7, 4), (blocker, 6, 4), (blocker, 7, 3)])
            moves = game.legal_moves()
            self.assertNotIn([7, 4, 5, 3], moves)
            self.assertNotIn([7, 4, 5, 5], moves)
            self.assertNotIn([7, 4, 6, 2], moves)
            self.assertIn([7, 4, 6, 6], moves)

    def test_elephant_eye_and_river(self):
        for blocker in ("P", "p"):
            game = position(KINGS + [("B", 7, 4), (blocker, 6, 3)])
            self.assertNotIn([7, 4, 5, 2], game.legal_moves())
            self.assertIn([7, 4, 5, 6], game.legal_moves())
        game = position(KINGS + [("B", 5, 2)])
        self.assertNotIn([5, 2, 3, 4], game.legal_moves())
        game = position(KINGS + [("b", 4, 6)], -1)
        self.assertNotIn([4, 6, 6, 4], game.legal_moves())

    def test_palace_and_advisor(self):
        game = position([("K", 7, 4), ("k", 0, 3), ("A", 8, 3)])
        moves = game.legal_moves()
        self.assertNotIn([7, 4, 6, 4], moves)
        self.assertIn([7, 4, 7, 5], moves)
        self.assertNotIn([7, 4, 8, 5], moves)
        self.assertNotIn([8, 3, 7, 2], moves)
        self.assertIn([8, 3, 9, 4], moves)

    def test_rook_cannot_jump_or_capture_own_piece(self):
        game = position(KINGS + [("R", 7, 0), ("P", 5, 0), ("r", 3, 0)])
        moves = game.legal_moves()
        self.assertIn([7, 0, 6, 0], moves)
        self.assertNotIn([7, 0, 5, 0], moves)
        self.assertNotIn([7, 0, 3, 0], moves)

    def test_cannon_requires_exactly_one_screen(self):
        base = KINGS + [("C", 7, 0), ("r", 3, 0)]
        game = position(base)
        self.assertNotIn([7, 0, 3, 0], game.legal_moves())
        self.assertIn([7, 0, 4, 0], game.legal_moves())
        for screen in ("P", "p"):
            game = position(base + [(screen, 5, 0)])
            self.assertIn([7, 0, 3, 0], game.legal_moves())
            self.assertNotIn([7, 0, 4, 0], game.legal_moves())
            game = position(base + [(screen, 5, 0), ("P", 4, 0)])
            self.assertNotIn([7, 0, 3, 0], game.legal_moves())

    def test_pawns_before_after_river_and_no_backward(self):
        for side, piece, before_row, after_row in ((1, "P", 5, 4), (-1, "p", 4, 5)):
            game = position(KINGS + [(piece, before_row, 0)], side)
            self.assertNotIn([before_row, 0, before_row, 1], game.legal_moves())
            self.assertIn([before_row, 0, after_row, 0], game.legal_moves())
            game = position(KINGS + [(piece, after_row, 0)], side)
            self.assertIn([after_row, 0, after_row, 1], game.legal_moves())
            self.assertNotIn([after_row, 0, before_row, 0], game.legal_moves())
        game = position(KINGS + [("P", 0, 0)])
        self.assertIn([0, 0, 0, 1], game.legal_moves())
        game.play([0, 0, 0, 1])
        self.assertEqual(game.board[0][1], "P")  # No pawn promotion.

    def test_facing_generals_filters_every_move(self):
        game = position([("K", 9, 4), ("k", 0, 4), ("R", 5, 4)])
        self.assertNotIn([5, 4, 5, 5], game.legal_moves())
        self.assertIn([5, 4, 4, 4], game.legal_moves())
        self.assertNotIn([5, 4, 0, 4], game.legal_moves())  # Never physically eat a general.
        before = game.snapshot()
        with self.assertRaises(ValueError):
            game.play([5, 4, 5, 5])
        self.assertEqual(game.snapshot(), before)

    def test_pinned_piece_and_response_to_check(self):
        game = position(KINGS + [("r", 5, 4), ("R", 7, 4)])
        self.assertNotIn([7, 4, 7, 5], game.legal_moves())
        self.assertIn([7, 4, 5, 4], game.legal_moves())
        game = position(KINGS + [("r", 5, 4), ("P", 6, 0)])
        self.assertTrue(game.is_in_check())
        before = game.snapshot()
        with self.assertRaises(ValueError):
            game.play([6, 0, 5, 0])
        self.assertEqual(game.snapshot(), before)

    def test_attack_detector_horse_and_cannon(self):
        game = position(KINGS + [("n", 7, 3)])
        self.assertTrue(game.is_in_check(1))
        game = position(KINGS + [("n", 7, 3), ("P", 8, 3)])
        self.assertFalse(game.is_in_check(1))
        game = position(KINGS + [("c", 4, 4)])
        self.assertFalse(game.is_in_check(1))
        game = position(KINGS + [("c", 4, 4), ("P", 7, 4)])
        self.assertTrue(game.is_in_check(1))
        game = position(KINGS + [("c", 4, 4), ("P", 7, 4), ("P", 6, 4)])
        self.assertFalse(game.is_in_check(1))

    def test_stalemate_is_a_loss(self):
        game = position([("k", 0, 4), ("K", 9, 4), ("P", 5, 4),
                         ("R", 1, 0), ("R", 2, 3), ("R", 2, 5)], -1)
        self.assertFalse(game.is_in_check())
        self.assertEqual(game.winner, 1)
        self.assertEqual(game.reason, "stalemate")
        self.assertEqual(game.legal_moves(), [])

    def test_checkmate_is_a_loss(self):
        game = position([("k", 0, 4), ("K", 9, 4), ("P", 5, 4),
                         ("R", 0, 0), ("R", 1, 0)], -1)
        self.assertTrue(game.is_in_check())
        self.assertEqual(game.winner, 1)
        self.assertEqual(game.reason, "checkmate")
        with self.assertRaises(ValueError):
            game.play([0, 4, 1, 4])

    def test_capture_undo_and_snapshot_isolation(self):
        game = position(KINGS + [("R", 7, 0), ("n", 7, 5)])
        before = game.snapshot()
        game.play([7, 0, 7, 5])
        self.assertEqual(game.history[-1], {"move": [7, 0, 7, 5], "side": 1, "piece": "R", "captured": "n"})
        copy = game.snapshot()
        copy["board"][7][5] = "."
        copy["history"][-1]["move"][0] = 99
        self.assertEqual(game.board[7][5], "R")
        self.assertEqual(game.history[-1]["move"][0], 7)
        game.undo(1)
        self.assertEqual(game.snapshot(), before)

    def test_repetition_contains_side_and_undo_restores_count(self):
        game = XiangqiGame()
        self.assertNotEqual(game._position_key(1), game._position_key(-1))
        cycle = ([9, 1, 7, 2], [0, 1, 2, 2], [7, 2, 9, 1], [2, 2, 0, 1])
        for move in cycle:
            game.play(move)
        self.assertIsNone(game.winner)
        after_cycle = game.snapshot()
        for move in cycle:
            game.play(move)
        self.assertEqual(game.winner, 0)
        self.assertEqual(game.reason, "repetition")
        game.undo(4)
        self.assertEqual(game.snapshot(), after_cycle)
        for move in cycle:
            game.play(move)
        self.assertEqual(game.winner, 0)
        game.undo(100)
        self.assertEqual(game.snapshot(), XiangqiGame().snapshot())

    def test_clone_and_read_operations_do_not_change_state(self):
        game = XiangqiGame()
        before = game.snapshot()
        positions_before = game._positions.copy()
        clone = game.clone()
        clone.play([6, 0, 5, 0])
        self.assertEqual(game.snapshot(), before)
        ranked = game.rank_moves(depth=2, limit=100)
        self.assertEqual(len(ranked), 44)
        self.assertEqual({tuple(x["move"]) for x in ranked}, {tuple(x) for x in game.legal_moves()})
        self.assertEqual([x["score"] for x in ranked], sorted((x["score"] for x in ranked), reverse=True))
        for entry in ranked:
            values = game.move_features(entry["move"])
            self.assertEqual(len(values), len(FEATURE_LABELS))
            self.assertTrue(all(math.isfinite(value) and 0 <= value <= 1 for value in values))
        self.assertEqual(game.snapshot(), before)
        self.assertEqual(game._positions, positions_before)

    def test_teacher_takes_free_rook_and_features_are_not_teacher_scores(self):
        game = position(KINGS + [("R", 7, 0), ("r", 7, 6)])
        move = [7, 0, 7, 6]
        self.assertEqual(game.rank_moves()[0]["move"], move)
        before = game.move_features(move)
        game._evaluate = lambda side: 12_345.0
        self.assertEqual(game.move_features(move), before)

    def test_teacher_marks_mate_and_undo_restores_terminal(self):
        game = position([("k", 0, 4), ("K", 9, 4), ("P", 5, 4),
                         ("R", 2, 0), ("R", 1, 1)])
        before = game.snapshot()
        ranked = game.rank_moves()
        self.assertTrue(ranked[0]["forced"])
        game.play(ranked[0]["move"])
        self.assertEqual(game.winner, 1)
        game.undo(1)
        self.assertEqual(game.snapshot(), before)

    def test_teacher_looks_past_last_ply_cannon_capture(self):
        game = XiangqiGame()
        game.play([6, 0, 5, 0])
        before = game.snapshot()
        positions = game._positions.copy()
        ranked = game.rank_moves(depth=2, limit=100)
        scores = {tuple(entry["move"]): entry["score"] for entry in ranked}
        # Both sides can launch a cannon onto a horse, but the nearby rook can
        # recapture. A depth-two leaf must not treat the opponent's shot as free.
        self.assertGreater(scores[(2, 1, 2, 4)], scores[(2, 1, 9, 1)])
        self.assertNotIn(ranked[0]["move"], ([2, 1, 9, 1], [2, 7, 9, 7]))
        self.assertEqual(game.snapshot(), before)
        self.assertEqual(game._positions, positions)

    def test_quiescence_checks_terminal_before_cutoff(self):
        for pieces, expected_reason in (
            ([("R", 0, 0), ("R", 1, 0)], "checkmate"),
            ([("R", 1, 0), ("R", 2, 3), ("R", 2, 5)], "stalemate"),
        ):
            game = position([("k", 0, 4), ("K", 9, 4), ("P", 5, 4)] + pieces, -1)
            self.assertEqual(game.reason, expected_reason)
            self.assertLessEqual(game._quiescence(-1, 0, game._positions.copy()), -1_000_000)

    def test_quiescence_searches_quiet_check_evasion(self):
        game = position(KINGS + [("r", 5, 4)])
        before = game.snapshot()
        visited = []

        def evaluation(side):
            visited.append(game._king(1))
            return 0.0

        game._evaluate = evaluation
        self.assertTrue(game.is_in_check(1))
        self.assertEqual(list(game._legal_iter(1, captures_only=True)), [])
        game._quiescence(1, 1, game._positions.copy())
        self.assertTrue(visited)
        self.assertNotIn((9, 4), visited)  # Cannot stand pat while still in check.
        self.assertEqual(game.snapshot(), before)

    def test_search_arguments_and_depth_cap(self):
        game = XiangqiGame()
        for kwargs in ({"depth": 0}, {"depth": True}, {"depth": 1.5}, {"limit": 0}, {"limit": False}):
            with self.assertRaises(ValueError):
                game.rank_moves(**kwargs)
        self.assertEqual(game.rank_moves(depth=3), game.rank_moves(depth=2))


if __name__ == "__main__":
    unittest.main()
