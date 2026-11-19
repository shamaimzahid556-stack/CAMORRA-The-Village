"""Regression: the real game still works end to end, and the chatbot never changes game state."""
from dataclasses import replace
import json
import random
import unittest

from tests.helpers import Game
from tests.test_chat_privacy import make_game


def fingerprint(gs):
    return json.dumps({
        "phase": gs.phase, "day": gs.day_number, "night": gs.night_number, "over": gs.game_over, "winner": gs.winner,
        "alive": [p.alive for p in gs.players], "roles": [p.role.name for p in gs.players if p.role],
        "turn": gs.night_turn_index, "vturn": gs.voting_turn_index, "ri": gs.role_reveal_index, "mv": gs.mafia_votes,
        "sl": gs.mafia_shortlist_ids, "doc": gs.doctor_target_id, "det": gs.detective_target_id, "dv": gs.day_votes,
        "self": gs.doctor_self_save_used, "na": {k: str(v) for k, v in gs.night_actions.items()},
        "hist": gs.mafia_action_history, "mk": gs.mafia_target_id, "killed": gs.night_killed_player_id,
    }, sort_keys=True, default=str)


def play_full_game(g, rng, chat_every=1):
    """Play to the end like the browser does. Chat is used all along and must never alter the game."""
    A = g.app
    # a whole simulated game sends hundreds of chat messages within a second: lift the (separately tested) global limit
    g.service.settings = replace(g.service.settings, global_chat_per_minute=100000)
    sid = None
    steps = 0
    while not g.gs.game_over and steps < 500:
        steps += 1
        ph = g.gs.phase
        before = fingerprint(g.gs)
        if steps % chat_every == 0:
            sid = g.service.open_session()["session_id"]
            g.service.handle_message(sid, "What should I do now?")
            g.service.handle_message(sid, "Is Ali the Mafia?")
            g.service.handle_message(sid, "How does voting work?")
            g.service.close_session(sid)
        assert fingerprint(g.gs) == before, f"chat changed the game state during {ph}"
        if ph == "NIGHT":
            g.ready()
            cur = g.night_actor()
            a, role = cur["player_id"], cur["role"]
            if role == "Mafia":
                if cur.get("stage") == "SHORTLIST":
                    ids = [t["id"] for t in cur["targets"]]
                    g.post(A.mafia_shortlist, "/api/night/mafia/shortlist",
                           A.MafiaShortlistRequest(actor_id=a, candidate_ids=rng.sample(ids, rng.randint(2, min(4, len(ids))))))
                    cur = g.night_actor()
                g.post(A.mafia_vote, "/api/night/mafia/vote", A.MafiaVoteRequest(actor_id=a, target_id=rng.choice([t["id"] for t in cur["targets"]])))
            elif role == "Doctor":
                ts = [t["id"] for t in cur["targets"] if cur["self_save_available"] or t["id"] != a]
                g.post(A.doctor_target, "/api/night/doctor", A.DoctorTargetRequest(actor_id=a, target_id=rng.choice(ts)))
            elif role == "Detective":
                g.post(A.detective_target, "/api/night/detective", A.DetectiveTargetRequest(actor_id=a, target_id=rng.choice([t["id"] for t in cur["targets"]])))
            else:
                g.post(A.villager_activity, "/api/night/villager", A.VillagerActivityRequest(actor_id=a, activity=rng.choice(cur["activities"])))
        elif ph == "DISCUSSION":
            g.post(A.morning, "/api/night/morning") if hasattr(A, "morning") else None
            g.post(A.discussion_start, "/api/day/discussion-start")
            g.post(A.start_voting, "/api/day/start-voting")                      # the old "Start Voting restarts the game" bug
            assert g.gs.phase == "VOTING", f"START VOTING left phase as {g.gs.phase}"
            assert g.gs.players and g.gs.phase != "ROLE_ASSIGNMENT"
        elif ph == "VOTING":
            d = A.day_current()
            v = d["voter"]["id"]
            ts = [p["id"] for p in d["players"] if p["alive"] and p["id"] != v and p["id"] not in d["forbidden_target_ids"]]
            g.post(A.day_vote, "/api/day/vote", A.DayVoteRequest(voter_id=v, target_id=rng.choice(ts)))
        elif ph == "ELIMINATION":
            g.post(A.continue_after_day_vote, "/api/day/continue")
        else:
            raise AssertionError(f"unexpected phase {ph}")
    return g.gs


class FullGames(unittest.TestCase):
    CONFIGS = [(6, 1), (7, 2), (8, 2), (9, 3), (10, 1), (12, 3), (15, 3)]

    def test_games_complete_with_a_winner_for_every_size(self):
        for n, m in self.CONFIGS:
            for seed in range(3):
                random.seed(seed * 100 + n)
                rng = random.Random(seed)
                g = make_game(names=[f"P{i}" for i in range(1, n + 1)], mafia=m)
                g.finish_role_assignment()
                gs = play_full_game(g, rng, chat_every=2)
                self.assertTrue(gs.game_over, (n, m, seed))
                self.assertIn(gs.winner, ("Civilians", "Mafia"))
                # chat is shut off on the results screen and every chat is gone
                self.assertFalse(g.service.status()["available"])
                self.assertEqual(g.service.sessions.count(), 0)

    def test_start_voting_advances_and_does_not_restart(self):
        g = make_game()
        g.finish_role_assignment()
        rng = random.Random(1)
        # play night 1 only
        while g.gs.phase == "NIGHT":
            g.ready(); g.do_night_action()
        if g.gs.phase == "DISCUSSION":
            players_before = [(p.name, p.role.name) for p in g.gs.players]
            g.post(g.app.discussion_start, "/api/day/discussion-start")
            g.post(g.app.start_voting, "/api/day/start-voting")
            self.assertEqual(g.gs.phase, "VOTING")
            self.assertEqual(players_before, [(p.name, p.role.name) for p in g.gs.players])   # roles NOT re-dealt

    def test_chat_state_resets_between_games(self):
        g = make_game()
        g.finish_role_assignment()
        g.ready()
        sid = g.service.open_session()["session_id"]
        g.service.handle_message(sid, "hello")
        # a brand-new game replaces the old one: the old chat's turn no longer matches
        g.post(g.app.start_game, "/api/start", g.app.StartGameRequest(total_players=6, player_names=list("ABCDEF"), mafia_count=1))
        with self.assertRaises(SessionExpired):
            g.service.handle_message(sid, "hello again")


from chatbot.sessions import SessionExpired  # noqa: E402

if __name__ == "__main__":
    unittest.main()
