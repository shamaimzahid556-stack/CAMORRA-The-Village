"""Regression tests for the hardening pass: rejected requests, private data timing, resume support,
.env parsing, chatbot smalltalk/guards. Route functions are called directly; the HTTP-level class at the
bottom runs only when FastAPI's TestClient (httpx) is installed."""
import os
import tempfile
import unittest
from pathlib import Path

from tests.helpers import Game, REAL_FASTAPI


class RejectedStartKeepsGame(unittest.TestCase):
    def _start(self, g, names):
        A = g.app
        return A.start_game(A.StartGameRequest(total_players=len(names), player_names=names, mafia_count=1))

    def test_duplicate_names_do_not_wipe_running_game(self):
        g = Game()
        with self.assertRaises(Exception):
            self._start(g, ["Ali", "ali", "Omar", "Hina", "Zain", "Maya"])
        self.assertEqual(len(g.gs.players), 6)
        self.assertEqual(g.gs.phase, "ROLE_ASSIGNMENT")

    def test_long_names_rejected_server_side(self):
        g = Game()
        with self.assertRaises(Exception):
            self._start(g, ["x" * 41, "Sara", "Omar", "Hina", "Zain", "Maya"])
        self.assertEqual(len(g.gs.players), 6)


class PrivateDataTiming(unittest.TestCase):
    def setUp(self):
        self.g = Game()
        self.g.finish_role_assignment()

    def test_preview_has_no_private_fields(self):
        A = self.g.app
        preview = A.night_current(preview=1)
        self.assertEqual(set(preview), {"phase", "night_number", "player_id", "player_name"})
        with self.assertRaises(Exception):           # full details are refused before I'M READY
            A.night_current()
        full = self.g.ready()
        self.assertIn("role", full)

    def test_night_ready_is_recorded_server_side(self):
        cur = self.g.ready()
        self.assertEqual(self.g.gs.night_ready_for, (self.g.gs.night_number, cur["player_id"]))

    def test_discussion_timer_does_not_restart(self):
        g, A = self.g, self.g.app
        g.gs.phase = "DISCUSSION"
        A.discussion_start()
        first = g.gs.discussion_started_at
        A.discussion_start()
        self.assertEqual(g.gs.discussion_started_at, first)

    def test_day_preview_hides_forbidden_ids(self):
        g, A = self.g, self.g.app
        g.gs.phase = "VOTING"
        g.gs.voting_turn_index = 0
        self.assertEqual(A.day_current(preview=1)["forbidden_target_ids"], [])

    def test_elimination_endpoint_for_resume(self):
        g, A = self.g, self.g.app
        victim = g.gs.players[0]
        g.gs.phase = "ELIMINATION"
        g.gs.eliminated_player_id = victim.player_id
        res = A.day_elimination()
        self.assertEqual(res["eliminated_player"]["name"], victim.name)
        self.assertIn("role", res["eliminated_player"])


class EnvParsing(unittest.TestCase):
    def _settings(self, text, encoding="utf-8", **extra):
        from chatbot import config
        keys = [k for k in os.environ if k.startswith("CAMORRA_") or k == "OPENAI_API_KEY"]
        saved = {k: os.environ.pop(k) for k in keys}
        try:
            with tempfile.TemporaryDirectory() as d:
                p = Path(d) / ".env"
                p.write_bytes(text.encode(encoding))
                config.load_dotenv_once(p)
                return config.load_settings()
        finally:
            for k in [k for k in os.environ if k.startswith("CAMORRA_")]:
                del os.environ[k]
            os.environ.update(saved)

    def test_inline_comments_are_ignored(self):
        s = self._settings("CAMORRA_LLM_TIMEOUT=20   # seconds\nCAMORRA_LLM_MODE=offline  # never call a model\n"
                           "CAMORRA_METRICS=off  # no counters\n")
        self.assertEqual(s.timeout, 20.0)
        self.assertEqual(s.llm_mode, "offline")
        self.assertFalse(s.metrics_enabled)

    def test_bad_numbers_fall_back_instead_of_crashing(self):
        s = self._settings("CAMORRA_LLM_TIMEOUT=soon\nCAMORRA_MAX_MESSAGES=lots\n")
        self.assertEqual(s.timeout, 20.0)
        self.assertEqual(s.max_messages_per_session, 40)

    def test_utf16_and_bom_files(self):
        self.assertEqual(self._settings("CAMORRA_LLM_MODEL=m16\n", "utf-16").model, "m16")
        self.assertEqual(self._settings("﻿CAMORRA_LLM_MODEL=mbom\n").model, "mbom")


class ChatbotFixes(unittest.TestCase):
    def test_smalltalk_does_not_swallow_questions(self):
        from chatbot.understanding import ABOUT_BOT, THANKS
        for q in ["nice what does detective do", "great how do I vote", "cool what is the doctor"]:
            self.assertIsNone(THANKS.match(q), q)
        for q in ["thanks!", "thank you so much", "ok cool"]:
            self.assertTrue(THANKS.match(q), q)
        for q in ["What are you allowed to do at night?", "What are you supposed to do as the doctor?"]:
            self.assertIsNone(ABOUT_BOT.search(q), q)
        self.assertTrue(ABOUT_BOT.search("who are you?"))

    def test_output_guard_covers_role_word_and_short_names(self):
        from chatbot.privacy import guard_output
        self.assertFalse(guard_output("Wolf is the Mafia", ["Wolf"]))
        self.assertFalse(guard_output("Al is a doctor", ["Al"]))
        self.assertTrue(guard_output("The Doctor can protect anyone.", ["Doctor", "Al"]))

    def test_roman_urdu_and_urdu_secret_requests(self):
        from chatbot.privacy import detect_secret_request as d
        for q in ["mafia kaun hai?", "kya Ali doctor hai", "مافیا کون ہے؟"]:
            self.assertEqual(d(q, ["Ali"]), "role_identity", q)
        self.assertIsNone(d("doctor kaun hota hai", ["Ali"]))

    def test_eval_on_empty_set_does_not_divide_by_zero(self):
        from chatbot.engine import Engine
        from chatbot.evaluation import run_eval
        r = run_eval(Engine(), {"single": [], "conversations": []})
        self.assertEqual(r["total"], 0)


@unittest.skipUnless(REAL_FASTAPI, "needs real FastAPI")
class HttpLevel(unittest.TestCase):
    def setUp(self):
        try:
            from fastapi.testclient import TestClient
        except Exception:
            self.skipTest("httpx not installed")
        from tests.helpers import load_app
        self.app = load_app()
        self.client = TestClient(self.app.app)

    def _start(self, names, mafia=1):
        return self.client.post("/api/start", json={"total_players": len(names), "player_names": names, "mafia_count": mafia})

    def test_start_validation_and_no_wipe(self):
        names = ["Ali", "Sara", "Omar", "Hina", "Zain", "Maya"]
        self.assertEqual(self._start(names).status_code, 200)
        self.assertEqual(self._start(["Ali", "ali", "Omar", "Hina", "Zain", "Maya"]).status_code, 422)
        self.assertEqual(self.client.get("/api/state").json()["phase"], "ROLE_ASSIGNMENT")

    def test_security_headers_and_cache(self):
        r = self.client.get("/")
        self.assertEqual(r.headers.get("x-content-type-options"), "nosniff")
        self.assertEqual(r.headers.get("cache-control"), "no-cache")

    def test_non_local_clients_are_refused(self):
        from fastapi.testclient import TestClient
        remote = TestClient(self.app.app, client=("203.0.113.9", 5000))
        self.assertEqual(remote.get("/api/state").status_code, 403)


if __name__ == "__main__":
    unittest.main()
