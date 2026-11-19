import json
import threading
import unittest
import urllib.error
import urllib.request
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

from tests.helpers import Game
from tests.test_chat_privacy import make_game, to_first_night_turn
from chatbot import llm
from chatbot.config import load_settings


def settings(**kw):
    return replace(load_settings(), llm_mode="llm", **kw)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self, n=-1): return json.dumps(self.payload).encode()[:n if n >= 0 else None]


OK = {"choices": [{"message": {"content": "A friendly answer."}}]}


class WhatIsSentToOpenAI(unittest.TestCase):
    def test_request_is_stateless_and_store_false(self):
        s = settings(base_url="https://api.openai.com/v1", api_key="sk-test", model="gpt-4o-mini")
        seen = {}

        def fake_urlopen(req, timeout=None):
            seen["url"], seen["headers"], seen["body"] = req.full_url, dict(req.header_items()), json.loads(req.data)
            return FakeResponse(OK)
        with mock.patch("urllib.request.urlopen", fake_urlopen):
            out = llm.complete(s, [{"role": "system", "content": "x"}, {"role": "user", "content": "hi"}])
        self.assertEqual(out, "A friendly answer.")
        self.assertEqual(seen["url"], "https://api.openai.com/v1/chat/completions")      # not the stateful Responses API
        self.assertIs(seen["body"]["store"], False)
        for forbidden in ("conversation", "thread_id", "previous_response_id", "metadata", "user"):
            self.assertNotIn(forbidden, seen["body"])
        self.assertEqual(seen["headers"]["Authorization"], "Bearer sk-test")
        self.assertIn("max_completion_tokens", seen["body"])

    def test_store_flag_not_sent_to_other_providers(self):
        s = settings(base_url="http://localhost:11434/v1", api_key="", model="llama3.2")
        seen = {}
        with mock.patch("urllib.request.urlopen", lambda req, timeout=None: (seen.update(b=json.loads(req.data), h=dict(req.header_items())), FakeResponse(OK))[1]):
            llm.complete(s, [{"role": "user", "content": "hi"}])
        self.assertNotIn("store", seen["b"]); self.assertIn("max_tokens", seen["b"])
        self.assertNotIn("Authorization", seen["h"])
        self.assertTrue(s.llm_configured)                          # a local server needs no key

    def test_unconfigured_means_offline(self):
        s = replace(load_settings(), llm_mode="auto", api_key="", base_url="https://api.openai.com/v1")
        self.assertFalse(s.llm_configured)
        self.assertFalse(replace(s, llm_mode="offline", api_key="k").llm_configured)

    def test_history_in_the_prompt_is_only_this_sessions(self):
        g = make_game()
        to_first_night_turn(g)
        g.ready()
        ctx = g.service._context()
        msgs = llm.build_messages("and now?", [], ctx, [("user", "q1"), ("assistant", "a1")])
        roles = [m["role"] for m in msgs]
        self.assertEqual(roles, ["system", "user", "assistant", "user"])
        self.assertIn("CAMORRA AI Companion", msgs[0]["content"])


class ErrorHandling(unittest.TestCase):
    def http_error(self, code, body=""):
        return urllib.error.HTTPError("u", code, "m", {}, mock.Mock(read=lambda: body.encode()))

    def test_key_errors_never_leak_the_key(self):
        s = settings(base_url="https://api.openai.com/v1", api_key="sk-LEAKME")
        with mock.patch("urllib.request.urlopen", side_effect=self.http_error(401, "bad key sk-LEAKME")):
            with self.assertRaises(llm.LLMError) as cm:
                llm.complete(s, [])
        self.assertNotIn("sk-LEAKME", str(cm.exception))

    def test_adapts_to_models_that_reject_temperature(self):
        s = settings(base_url="https://api.openai.com/v1", api_key="k")
        bodies = []

        def fake(req, timeout=None):
            bodies.append(json.loads(req.data))
            if "temperature" in bodies[-1]:
                raise self.http_error(400, '{"error":"Unsupported value: temperature"}')
            return FakeResponse(OK)
        with mock.patch("urllib.request.urlopen", fake):
            self.assertEqual(llm.complete(s, []), "A friendly answer.")
        self.assertEqual(len(bodies), 2); self.assertNotIn("temperature", bodies[1])

    def test_network_and_timeout_errors_become_llmerror(self):
        s = settings(api_key="k")
        for exc in (urllib.error.URLError("down"), TimeoutError(), ConnectionResetError()):
            with mock.patch("urllib.request.urlopen", side_effect=exc):
                with self.assertRaises(llm.LLMError):
                    llm.complete(s, [])

    def test_service_falls_back_to_the_rulebook_when_the_model_fails(self):
        g = make_game()
        g.service.settings = replace(g.service.settings, llm_mode="llm", api_key="k")
        def boom(*a, **k): raise llm.LLMError("The AI service is busy or over its quota right now.")
        g.service._llm_complete = boom
        to_first_night_turn(g)
        sid = g.service.open_session()["session_id"]
        r = g.service.handle_message(sid, "What does the Detective do?")
        self.assertEqual(r["reply"], "Sorry, I couldn't process that just now. Please try again.")   # MOCKED provider failure
        self.assertNotRegex(r["reply"], r"(?i)quota|busy|rulebook|model|api")


class RealHttpServer(unittest.TestCase):
    """An actual HTTP round trip against a throw-away local server."""

    def test_round_trip_and_param_adaptation(self):
        log = []

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                log.append((self.path, body))
                if "max_tokens" in body:                    # pretend: this model wants max_completion_tokens
                    self.send_response(400); self.end_headers()
                    self.wfile.write(b'{"error":"Unsupported parameter: max_tokens. Use max_completion_tokens"}')
                    return
                self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
                self.wfile.write(json.dumps({"choices": [{"message": {"content": "served locally"}}]}).encode())
            def log_message(self, *a): pass

        srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            s = settings(base_url=f"http://127.0.0.1:{srv.server_port}/v1", api_key="", model="local")
            self.assertEqual(llm.complete(s, [{"role": "user", "content": "hi"}]), "served locally")
        finally:
            srv.shutdown()
            srv.server_close()
        self.assertEqual(log[0][0], "/v1/chat/completions")
        self.assertIn("max_tokens", log[0][1]); self.assertIn("max_completion_tokens", log[1][1])


if __name__ == "__main__":
    unittest.main()
