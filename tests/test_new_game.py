"""Regression: after a match ends, NEW GAME must start a completely fresh match without restarting the server.

Root cause that these tests guard: the NEW GAME button only reloaded the page. Once the page resumes the server's
finished game (refresh-resume), a reload shows the game-over screen again, so no new game could ever be set up.
The button now asks the server to discard the finished match (POST /api/new-game)."""
import random
import unittest

from tests.helpers import Game
from tests.test_game_flow import play_full_game, fingerprint


def snapshot_clean(gs):
    return (gs.phase, gs.players, gs.day_number, gs.night_number, gs.game_over, gs.winner, gs.day_votes, gs.mafia_votes,
            gs.mafia_shortlist_ids, gs.doctor_target_id, gs.detective_target_id, gs.public_log, gs.night_actions,
            gs.discussion_active, gs.discussion_started_at, gs.eliminated_player_id, gs.vote_tie, gs.morning_ready,
            gs.doctor_self_save_used, gs.night_ready_for)


class SecondMatch(unittest.TestCase):
    def finished_game(self, seed=3, names=None, mafia=1):
        g = Game(names=names, mafia=mafia)
        g.finish_role_assignment()
        play_full_game(g, random.Random(seed), chat_every=50)
        self.assertTrue(g.gs.game_over)
        self.assertEqual(g.gs.phase, "GAME_OVER")
        return g

    def test_new_game_discards_the_finished_match_completely(self):
        g = self.finished_game()
        A = g.app
        old_names = [p.name for p in g.gs.players]
        out = g.post(A.new_game, "/api/new-game")
        self.assertEqual(out["phase"], "SETUP")
        fresh = A.game_state
        self.assertEqual(snapshot_clean(fresh), snapshot_clean(type(fresh)()))
        self.assertEqual(A.state()["phase"], "SETUP")
        self.assertEqual(A.state()["players"], [])
        self.assertEqual(old_names, ["Ali", "Sara", "Omar", "Hina", "Zain", "Maya"])

    def test_second_match_starts_and_follows_the_same_rules(self):
        g = self.finished_game()
        A = g.app
        g.post(A.new_game, "/api/new-game")
        names = ["Nadia", "Faisal", "Zoya", "Imran", "Rida", "Kamran", "Laiba"]
        res = g.post(A.start_game, "/api/start", A.StartGameRequest(total_players=7, player_names=names, mafia_count=2))
        self.assertEqual(res["phase"], "ROLE_ASSIGNMENT")
        gs = A.game_state
        self.assertEqual([p.name for p in gs.players], names)
        roles = sorted(p.role.name for p in gs.players)
        self.assertEqual(roles, ["Detective", "Doctor", "Mafia", "Mafia", "Villager", "Villager", "Villager"])
        self.assertEqual(snapshot_clean(gs)[2:5], (0, 0, False))
        g.names = names
        g.finish_role_assignment()
        play_full_game(g, random.Random(11), chat_every=50)         # the whole second match plays to a normal end
        self.assertTrue(A.game_state.game_over)
        self.assertIn(A.game_state.winner, ("Mafia", "Civilians"))

    def test_start_directly_after_game_over_also_works_and_is_clean(self):
        g = self.finished_game(seed=5)
        A = g.app
        g.post(A.start_game, "/api/start",
               A.StartGameRequest(total_players=6, player_names=["A1", "B2", "C3", "D4", "E5", "F6"], mafia_count=1))
        gs = A.game_state
        self.assertEqual((gs.phase, gs.game_over, gs.winner, gs.public_log, gs.day_votes), ("ROLE_ASSIGNMENT", False, None, [], {}))

    def test_invalid_setup_after_game_over_is_rejected_and_changes_nothing(self):
        g = self.finished_game(seed=4)
        A = g.app
        before = fingerprint(A.game_state)
        bad_requests = [
            lambda: A.StartGameRequest(total_players=6, player_names=["a", "A", "c", "d", "e", "f"], mafia_count=1),
            lambda: A.StartGameRequest(total_players=6, player_names=["a", "b", "c", "d", "e", ""], mafia_count=1),
            lambda: A.StartGameRequest(total_players=6, player_names=["a", "b", "c", "d", "e", "x" * 50], mafia_count=1),
            lambda: A.StartGameRequest(total_players=6, player_names=["a", "b", "c", "d", "e", "f"], mafia_count=5),
        ]
        for make in bad_requests:
            with self.assertRaises(Exception):
                A.start_game(make())
        self.assertEqual(fingerprint(A.game_state), before)
        self.assertEqual(A.game_state.phase, "GAME_OVER")

    def test_repeated_new_game_and_start_calls_leave_one_consistent_game(self):
        g = self.finished_game(seed=6)
        A = g.app
        for _ in range(3):
            g.post(A.new_game, "/api/new-game")
        req = A.StartGameRequest(total_players=6, player_names=["a1", "b2", "c3", "d4", "e5", "f6"], mafia_count=1)
        g.post(A.start_game, "/api/start", req)
        g.post(A.start_game, "/api/start", req)         # a repeated click: still exactly one fully initialised game
        gs = A.game_state
        self.assertEqual(len(gs.players), 6)
        self.assertEqual(len({p.player_id for p in gs.players}), 6)
        self.assertEqual(sorted(p.role.name for p in gs.players).count("Mafia"), 1)
        self.assertEqual(gs.phase, "ROLE_ASSIGNMENT")
        self.assertEqual(gs.role_reveal_index, 0)

    def test_private_state_and_chat_sessions_do_not_leak_into_the_next_match(self):
        g = Game()
        g.finish_role_assignment()
        g.ready()
        sid = g.service.open_session()["session_id"]
        self.assertIsNotNone(g.chat.tracker.night_ready_for)
        g.post(g.app.new_game, "/api/new-game")
        self.assertEqual(g.service.sessions.count(), 0)
        self.assertIsNone(g.chat.tracker.role_revealed_for)
        self.assertIsNone(g.chat.tracker.night_ready_for)
        g.post(g.app.start_game, "/api/start",
               g.app.StartGameRequest(total_players=6, player_names=["a1", "b2", "c3", "d4", "e5", "f6"], mafia_count=1))
        self.assertIsNone(g.service._context().role)       # nobody has seen a role yet in the new match
        with self.assertRaises(Exception):
            g.service.handle_message(sid, "What does the Doctor do?")   # the old chat session is gone

    def test_game_over_still_blocks_actions_until_a_new_game_is_started(self):
        g = self.finished_game(seed=9)
        with self.assertRaises(Exception):
            g.app.night_ready(g.app.NightReadyRequest(player_id=1))


if __name__ == "__main__":
    unittest.main()
