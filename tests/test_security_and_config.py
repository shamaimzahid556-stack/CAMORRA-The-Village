"""Security, configuration and resilience tests that need no network and no real FastAPI: the ASGI middleware is driven
directly, the model client is driven through urllib mocks."""
import asyncio
import base64
import hashlib
import io
import json
import re
import unittest
import urllib.error
from dataclasses import replace
from pathlib import Path
from unittest import mock

import security
from chatbot import config, language, llm
from chatbot.sessions import RateLimited
from tests.quality import RecordingLLM, new_game, to_turn, ask

ROOT = Path(__file__).resolve().parent.parent


def run_asgi(app, method="POST", headers=(), body_chunks=(b"",), path="/api/x"):
    """Drive an ASGI app once; return (status, headers, body, app_saw_bytes)."""
    sent, seen = [], {"n": 0}
    chunks = list(body_chunks)

    async def receive():
        if chunks:
            c = chunks.pop(0)
            seen["n"] += len(c)
            return {"type": "http.request", "body": c, "more_body": bool(chunks)}
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "method": method, "path": path, "headers": [(k.encode(), v.encode()) for k, v in headers],
             "client": ("127.0.0.1", 1)}
    asyncio.run(app(scope, receive, send))
    start = next(m for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return start["status"], dict(start["headers"]), body, seen["n"]


async def echo_app(scope, receive, send):
    total = 0
    while True:
        m = await receive()
        if m["type"] != "http.request":
            break
        total += len(m.get("body", b""))
        if not m.get("more_body"):
            break
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/plain")]})
    await send({"type": "http.response.body", "body": str(total).encode()})


class RequestSizeLimit(unittest.TestCase):
    def setUp(self):
        self.app = security.BodyLimitMiddleware(echo_app, max_bytes=100)

    def test_small_body_passes(self):
        status, _, body, _ = run_asgi(self.app, headers=[("content-length", "50")], body_chunks=[b"x" * 50])
        self.assertEqual((status, body), (200, b"50"))

    def test_declared_oversize_is_rejected_before_the_app_runs(self):
        status, _, body, seen = run_asgi(self.app, headers=[("content-length", "101")], body_chunks=[b"x" * 101])
        self.assertEqual(status, 413)
        self.assertEqual(json.loads(body)["detail"], "The request is too large.")
        self.assertEqual(seen, 0)                                  # the body was never even read

    def test_streamed_oversize_without_content_length_is_rejected(self):
        status, *_ = run_asgi(self.app, body_chunks=[b"x" * 60, b"x" * 60])
        self.assertEqual(status, 413)

    def test_garbage_content_length_is_a_400_not_a_crash(self):
        status, *_ = run_asgi(self.app, headers=[("content-length", "abc")])
        self.assertEqual(status, 400)

    def test_get_requests_are_not_touched(self):
        status, *_ = run_asgi(self.app, method="GET")
        self.assertEqual(status, 200)


class Headers(unittest.TestCase):
    def test_headers_present_and_not_duplicated(self):
        app = security.SecurityHeadersMiddleware(echo_app)
        _, h, *_ = run_asgi(app, method="GET")
        for name in (b"content-security-policy", b"x-content-type-options", b"referrer-policy", b"x-frame-options",
                     b"permissions-policy"):
            self.assertIn(name, h)
        self.assertIn(b"frame-ancestors 'none'", h[b"content-security-policy"])
        self.assertNotIn(b"unsafe-eval", h[b"content-security-policy"])

    def test_csp_allows_exactly_the_inline_handler_the_page_uses(self):
        """The one inline event handler in index.html must be covered by its hash, and no other inline handler or inline
        script may exist (they would be blocked by the policy and silently break the page)."""
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        handlers = re.findall(r"\son[a-z]+=\"([^\"]*)\"", html)
        self.assertTrue(handlers)
        allowed = {"sha256-" + base64.b64encode(hashlib.sha256(h.encode()).digest()).decode() for h in handlers}
        self.assertTrue(all(f"'{a}'" in security.CSP for a in allowed), allowed)
        self.assertEqual(re.findall(r"<script(?![^>]*\bsrc=)[^>]*>", html), [])      # no inline <script> blocks

    def test_hsts_only_when_declared(self):
        with mock.patch.dict("os.environ", {"CAMORRA_HSTS": "1"}):
            _, h, *_ = run_asgi(security.SecurityHeadersMiddleware(echo_app), method="GET")
        self.assertIn(b"strict-transport-security", h)
        _, h, *_ = run_asgi(security.SecurityHeadersMiddleware(echo_app), method="GET")
        self.assertNotIn(b"strict-transport-security", h)


def settings(**kw):
    base = replace(config.load_settings(), llm_mode="auto", base_url="https://api.example.com/v1", api_key="k",
                   model="m", timeout=5.0, total_deadline=30.0, max_retries=2, max_response_chars=4000)
    return replace(base, **kw)


class EndpointValidation(unittest.TestCase):
    def test_remote_http_is_refused_and_turns_the_model_off(self):
        s = settings(base_url="http://api.example.com/v1")
        self.assertIn("https", s.endpoint_problem)
        self.assertFalse(s.llm_configured)
        self.assertEqual(s.mode_reason, "unsafe_endpoint")
        with mock.patch("urllib.request.urlopen") as op:
            with self.assertRaises(llm.LLMError):
                llm.complete(s, [])
            op.assert_not_called()                                 # the key was never sent anywhere

    def test_local_http_and_remote_https_are_accepted(self):
        for url in ("http://localhost:11434/v1", "http://127.0.0.1:1234/v1", "https://api.groq.com/openai/v1"):
            self.assertIsNone(settings(base_url=url).endpoint_problem, url)

    def test_credentials_in_the_url_and_odd_schemes_are_refused(self):
        for url in ("https://user:pw@api.example.com/v1", "file:///etc/passwd", "ftp://x/y", "https:///v1"):
            self.assertIsNotNone(settings(base_url=url).endpoint_problem, url)

    def test_validate_settings_reports_problems(self):
        self.assertTrue(config.validate_settings(settings(base_url="http://evil.example.com/v1")))
        self.assertEqual(config.validate_settings(settings()), [])

    def test_out_of_range_numbers_fall_back(self):
        with mock.patch.dict("os.environ", {"CAMORRA_LLM_RETRIES": "99", "CAMORRA_LLM_DEADLINE": "0", "CAMORRA_SCOPE": "everything"}):
            s = config.load_settings()
        self.assertEqual((s.max_retries, s.total_deadline, s.scope), (2, 30.0, "game"))


class Resilience(unittest.TestCase):
    OK = {"choices": [{"message": {"content": "fine"}}]}

    class Resp:
        def __init__(self, payload=None, raw=None):
            self.raw = raw if raw is not None else json.dumps(payload).encode()
        def read(self, n=-1): return self.raw[:n if n >= 0 else None]
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def http(self, code, headers=None):
        return urllib.error.HTTPError("u", code, "m", headers or {}, io.BytesIO(b"{}"))

    def test_transient_errors_are_retried_with_exponential_backoff_then_succeed(self):
        calls, sleeps = [], []
        def fake(req, timeout=None):
            calls.append(timeout)
            if len(calls) < 3:
                raise self.http(503)
            return self.Resp(self.OK)
        with mock.patch("urllib.request.urlopen", fake):
            self.assertEqual(llm.complete(settings(), [], _sleep=sleeps.append), "fine")
        self.assertEqual(len(calls), 3)
        self.assertEqual(sleeps, [0.5, 1.0])

    def test_retries_are_bounded(self):
        calls = []
        def fake(req, timeout=None):
            calls.append(1)
            raise self.http(503)
        with mock.patch("urllib.request.urlopen", fake):
            with self.assertRaises(llm.LLMError):
                llm.complete(settings(max_retries=1), [], _sleep=lambda s: None)
        self.assertEqual(len(calls), 2)                            # first try + exactly one retry

    def test_permanent_errors_are_not_retried(self):
        for code in (401, 404, 422):
            calls = []
            def fake(req, timeout=None):
                calls.append(1)
                raise self.http(code)
            with mock.patch("urllib.request.urlopen", fake):
                with self.assertRaises(llm.LLMError):
                    llm.complete(settings(), [], _sleep=lambda s: None)
            self.assertEqual(len(calls), 1, code)

    def test_total_deadline_stops_retrying(self):
        now = {"t": 0.0}
        def clock(): return now["t"]
        def sleep(s): now["t"] += s
        def fake(req, timeout=None):
            now["t"] += 4.0
            raise self.http(503)
        with mock.patch("urllib.request.urlopen", fake):
            with self.assertRaises(llm.LLMError):
                llm.complete(settings(max_retries=5, total_deadline=6.0), [], _sleep=sleep, _clock=clock)
        self.assertLessEqual(now["t"], 6.0 + 4.0)                  # never keeps going past the deadline by more than one attempt

    def test_oversized_provider_response_is_refused_and_answers_are_capped(self):
        with mock.patch("urllib.request.urlopen", lambda req, timeout=None: self.Resp(raw=b"x" * (llm.MAX_BODY_BYTES + 50))):
            with self.assertRaises(llm.LLMError) as cm:
                llm.complete(settings(), [])
        self.assertIn("large", str(cm.exception))
        long = {"choices": [{"message": {"content": "a" * 9000}}]}
        with mock.patch("urllib.request.urlopen", lambda req, timeout=None: self.Resp(long)):
            self.assertEqual(len(llm.complete(settings(max_response_chars=500), [])), 500)

    def test_provider_bug_does_not_crash_the_chat(self):
        def boom(*a, **k): raise ValueError("provider bug with sk-SECRET inside")
        g = new_game(boom, scope="general")
        to_turn(g, "Ali")
        reply = ask(g, "Explain recursion")[0]["reply"]
        self.assertNotIn("sk-SECRET", reply)
        self.assertRegex(reply, r"(?i)AI model|couldn't|can't|unexpected")


class GlobalRateLimit(unittest.TestCase):
    def test_many_sessions_share_one_budget(self):
        g = new_game()
        g.service.settings = replace(g.service.settings, global_chat_per_minute=5)
        opened = 0
        with self.assertRaises(RateLimited):
            for _ in range(20):                                    # opening many sessions does not reset the allowance
                g.service.open_session()
                opened += 1
        self.assertEqual(opened, 5)

    def test_window_slides(self):
        t = {"now": 0.0}
        g = new_game()
        g.service._clock = lambda: t["now"]
        g.service.settings = replace(g.service.settings, global_chat_per_minute=2)
        g.service.open_session(); g.service.open_session()
        with self.assertRaises(RateLimited):
            g.service.open_session()
        t["now"] = 61.0
        g.service.open_session()                                   # a minute later the budget is back


class Scope(unittest.TestCase):
    def test_default_is_camorra_only_even_with_a_model(self):
        stub = RecordingLLM("SHOULD NOT BE USED")
        g = new_game(stub)
        to_turn(g, "Ali")
        replies = [r["reply"] for r in ask(g, ["Write a Python function for binary search", "Translate hello into Urdu",
                                               "What is the capital of France?"])]
        self.assertEqual(stub.calls, [])                           # unrelated requests never reach the model
        for r in replies:
            self.assertNotIn("def ", r)
            self.assertNotRegex(r, r"(?i)\bparis\b|\bhello\b.*\bسلام|binary search")        # nothing of the general answer
            self.assertRegex(r, r"(?i)not sure|CAMORRA")

    def test_game_questions_still_reach_the_model(self):
        stub = RecordingLLM("The Detective investigates.")
        g = new_game(stub)
        to_turn(g, "Ali")
        r = ask(g, "Can you walk me through why the Detective matters for strategy?")[0]
        self.assertEqual(r["mode"], "llm")
        system = stub.calls[0][0]["content"]
        self.assertIn("you help with CAMORRA only", system)
        self.assertNotIn("SCOPE OVERRIDE", system)

    def test_roman_urdu_redirect_is_in_roman_urdu(self):
        g = new_game()
        r = ask(g, "mujhe python mein binary search ka code likh kar do")[0]["reply"]
        self.assertRegex(r, r"(?i)madad|hoon")


class LanguageSupport(unittest.TestCase):
    CASES = {
        "Detective ka kya kaam hota hai?": "roman_urdu",
        "Agar mafia tie kar dein voting mein to kya hoga?": "roman_urdu",
        "Doctor apne aap ko save kar sakta hai?": "roman_urdu",
        "Mujhe game samjhao, main new hun.": "roman_urdu",
        "Agar kisi player par shak ho to kya karna chahiye?": "roman_urdu",
        "ڈاکٹر کیا کرتا ہے؟": "urdu",
        "What does the Detective do?": "english",
        "How do I know what to do next?": "english",
        "What is the main rule of the game?": "english",
    }

    def test_detection(self):
        for text, expected in self.CASES.items():
            self.assertEqual(language.detect(text), expected, text)

    def test_roman_urdu_questions_find_the_right_rulebook_topic_offline(self):
        g = new_game()
        to_turn(g, "Zain")                                          # a Villager: role context must not hijack the topic
        expect = {"Detective ka kya kaam hota hai?": "investigat", "Doctor apne aap ko save kar sakta hai?": "yourself|themselves",
                  "Agar mafia tie kar dein voting mein to kya hoga?": "tied|tie", "ڈاکٹر کیا کرتا ہے؟": "protect"}
        for q, pat in expect.items():
            reply = ask(g, q)[0]["reply"].lower()
            self.assertRegex(reply, pat, q)

    def test_model_is_told_to_answer_in_the_players_language(self):
        stub = RecordingLLM("Jawab.")
        g = new_game(stub)
        to_turn(g, "Ali")
        ask(g, "Detective ka kya kaam hota hai?")
        system = stub.calls[0][0]["content"]
        self.assertIn("Pakistani Roman Urdu", system)
        self.assertIn("not Hindi", system)
        self.assertEqual(stub.calls[0][-1]["content"], "Detective ka kya kaam hota hai?")     # the original message, unmodified

    def test_english_prompt_has_no_language_instruction(self):
        stub = RecordingLLM("ok")
        g = new_game(stub)
        to_turn(g, "Ali")
        ask(g, "What does the Detective do?")
        self.assertNotIn("The player is writing in", stub.calls[0][0]["content"])


class Health(unittest.TestCase):
    def test_health_endpoints_reveal_nothing_private(self):
        from tests.helpers import Game
        g = Game()
        A = g.app
        self.assertEqual(A.healthz(), {"status": "ok"})
        ready = A.readyz()
        text = json.dumps(getattr(ready, "body", None) or getattr(ready, "content", None) or ready, default=str)
        for secret in ("api_key", "sk-", "Ali", "role"):
            self.assertNotIn(secret, text)


if __name__ == "__main__":
    unittest.main()
