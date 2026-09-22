import copy
import json
import queue
import tempfile
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from board_games import GamesSession
from lab import LabService


class GameSessionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.events = []
        self.session = GamesSession(self.directory.name, self.events.append)

    def tearDown(self):
        self.session.close()
        self.directory.cleanup()

    def command(self, name, **payload):
        return self.session.command(name, {"revision": self.session.revision, **payload})["game"]

    def test_play_undo_keeps_teacher_learning_without_outcome(self):
        state = self.command("move", move=[7, 7])
        self.assertEqual(len(state["history"]), 2)
        self.assertGreater(state["memory"]["teacher_examples"], 0)
        learned = copy.deepcopy(self.session.store.models["gomoku"].to_dict())
        state = self.command("undo")
        self.assertEqual(len(state["history"]), 0)
        self.assertEqual(self.session.store.models["gomoku"].to_dict(), learned)
        self.assertEqual(state["memory"]["outcome_examples"], 0)
        self.assertEqual(self.session.trace, [])
        self.assertEqual([e["kind"] for e in self.events], ["human_move", "ai_move", "undo"])

    def test_invalid_and_stale_requests_are_atomic(self):
        before = self.session.snapshot()
        for payload in ({"revision": -1, "move": [7, 7]}, {"revision": True, "move": [7, 7]},
                        {"revision": 0, "move": [False, 1]}, {"revision": 0, "move": [-1, 1]}):
            with self.assertRaises(ValueError):
                self.session.command("move", payload)
            self.assertEqual(self.session.snapshot(), before)

    def test_save_failure_rolls_back_board_memory_and_events(self):
        before = self.session.snapshot()
        model = self.session.store.models["gomoku"].to_dict()
        with patch.object(self.session.store, "save", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.command("move", move=[7, 7])
        self.assertEqual(self.session.snapshot(), before)
        self.assertEqual(self.session.store.models["gomoku"].to_dict(), model)
        self.assertEqual(self.events, [])

    def test_human_second_opening_undo_preserves_ai_opening(self):
        state = self.command("new", human_side=-1, depth=1)
        self.assertEqual(state["turn"], -1)
        self.assertEqual(len(state["history"]), 1)
        self.assertFalse(state["can_undo"])
        state = self.command("move", move=[7, 8])
        self.assertEqual(len(state["history"]), 3)
        state = self.command("undo")
        self.assertEqual(len(state["history"]), 1)
        self.assertEqual(state["turn"], -1)

    def test_coach_changes_memory_without_moving_and_freeze_uses_search(self):
        self.command("move", move=[7, 7])
        before = self.session.game.snapshot()
        state = self.command("coach")
        self.assertEqual(self.session.game.snapshot(), before)
        self.assertLess(state["coach"]["after"], state["coach"]["before"])
        self.command("learning", enabled=False)
        weights = self.session.store.models["gomoku"].to_dict()
        move = self.session.game.legal_moves()[0]
        state = self.command("move", move=move)
        self.assertEqual(state["analysis"]["source"], "search")
        with self.assertRaises(ValueError):
            self.command("coach")
        self.command("resign")
        self.assertEqual(self.session.store.models["gomoku"].to_dict(), weights)

    def test_completed_game_feedback_once_and_reload(self):
        self.command("move", move=[7, 7])
        state = self.command("resign")
        self.assertEqual(state["reason"], "resign")
        self.assertEqual(state["memory"]["outcome_examples"], 1)
        self.assertEqual(state["saved_games"], 1)
        for name in ("resign", "undo", "move"):
            with self.assertRaises(ValueError):
                self.command(name, move=[0, 0])
        expected = self.session.store.models["gomoku"].to_dict()
        self.session.close()
        with self.assertRaises(RuntimeError):
            self.command("new")
        self.session = GamesSession(self.directory.name)
        self.assertEqual(self.session.store.models["gomoku"].to_dict(), expected)
        self.assertEqual(self.session.store.records[0]["reason"], "resign")
        self.assertEqual(len(self.session.store.records[0]["moves"]), 2)

    def test_new_does_not_award_unfinished_outcome(self):
        self.command("move", move=[7, 7])
        state = self.command("new")
        self.assertEqual(state["memory"]["outcome_examples"], 0)
        self.assertEqual(state["saved_games"], 0)

    def test_network_can_change_candidate_choice_but_not_legality(self):
        # Counterfactual labels test causal influence, NOT stronger play.
        for move in [[7,7],[6,7],[7,8],[6,8],[8,6],[5,9]]:
            self.session.game.play(move)
        choose = lambda rows: max(rows, key=lambda r: (r["combined_value"], r["score"]))["move"]
        rows, _ = self.session._rank()
        self.assertEqual(choose(rows), [7, 6])
        self.session.store.models["gomoku"].learn_batch(
            [(r["features"], .9 if r["move"] == [7, 9] else -.9) for r in rows], rounds=20)
        changed, _ = self.session._rank()
        self.assertEqual(choose(changed), [7, 9])
        self.assertIn(choose(changed), self.session.game.legal_moves())

    def test_forced_win_overrides_learned_bias(self):
        self.session.human_side = -1
        for col in range(4):
            self.session.game.board[5][col] = 1
        model = self.session.store.models["gomoku"]
        model.weights = [-3.] * len(model.weights)
        events = []
        self.session._ai_move(events)
        self.assertEqual(self.session.game.winner, 1)
        self.assertEqual(self.session.analysis["move"], [5, 4])
        self.assertEqual(self.session.analysis["source"], "tactical")

    def test_xiangqi_roundtrip_and_learning_independence(self):
        gomoku = self.session.store.models["gomoku"].to_dict()
        state = self.command("new", kind="xiangqi", depth=1)
        self.assertEqual(len(state["legal_moves"]), 44)
        state = self.command("move", move=[6, 0, 5, 0])
        self.assertEqual(len(state["history"]), 2)
        self.assertEqual(state["turn"], 1)
        self.assertEqual(self.session.store.models["gomoku"].to_dict(), gomoku)
        state = self.command("undo")
        self.assertEqual(len(state["history"]), 0)
        self.assertEqual(len(state["legal_moves"]), 44)


class PetBridgeTests(unittest.TestCase):
    def test_board_event_updates_expression_without_behavior_weight_reward(self):
        from test_interaction import stub_app
        from engine import PetEngine
        app = stub_app()
        app.engine.body["idle"] = 500.0
        before = app.engine.brain.to_dict()
        for kind in ("start", "human_move", "ai_move", "finish"):
            app.handle_board_event({"kind": kind, "message": "棋桌测试", "game": "gomoku"})
        self.assertEqual(app.engine.body["idle"], 0.0)
        self.assertEqual(app.engine.brain.to_dict(), before)
        self.assertEqual(app.interaction.effect, "praise")
        self.assertEqual(app.save.call_count, 2)
        restored = PetEngine.from_dict(json.loads(json.dumps(app.engine.to_dict())))
        self.assertEqual(restored.memory[-1]["kind"], "board_game")


class GameHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.events = queue.SimpleQueue()
        cls.service = LabService(game_data_dir=cls.directory.name, on_game_event=cls.events.put).start()

    @classmethod
    def tearDownClass(cls):
        cls.service.stop()
        cls.directory.cleanup()

    def request(self, route, payload=None, token=True):
        req = Request(self.service.url + route, headers={
            "X-Lab-Token": self.service.token if token else "",
            "Content-Type": "application/json"},
            data=None if payload is None else json.dumps(payload).encode())
        return urlopen(req, timeout=15)

    def test_page_api_move_and_unauthorized_request(self):
        with self.request("games") as response:
            page = response.read().decode()
        self.assertIn("和小果下一盘", page)
        self.assertNotIn("__BOOT__", page)
        with self.assertRaises(HTTPError) as error:
            self.request("api/games/state", token=False)
        self.assertEqual(error.exception.code, 403)
        error.exception.close()
        with self.request("api/games/state") as response:
            state = json.load(response)["game"]
        with self.request("api/games/move", {"move": [7, 7], "revision": state["revision"]}) as response:
            state = json.load(response)["game"]
        self.assertEqual(len(state["history"]), 2)
        self.assertGreater(state["memory"]["teacher_examples"], 0)
        self.assertEqual(self.events.get_nowait()["kind"], "human_move")
        with self.assertRaises(HTTPError) as error:
            self.request("api/games/move", {"move": [0, 0], "revision": -1})
        self.assertEqual(error.exception.code, 400)
        error.exception.close()

    def test_stopping_service_does_not_create_memory_session(self):
        with tempfile.TemporaryDirectory() as directory:
            service = LabService(game_data_dir=directory)
            service.stop()
            with self.assertRaises(RuntimeError):
                service.get_games()
            self.assertIsNone(service.games)


if __name__ == "__main__":
    unittest.main()
