"""FastAPI wiring for the AI Companion. Adds routes under /api/ai/chat/* only; every existing
game route is untouched.

    GET  /api/ai/chat/status     is the chat available, and whether the chat can be opened (no developer details)
    POST /api/ai/chat/session    open a new private chat (destroys any other chat)
    POST /api/ai/chat            send a message  {session_id, message, style}
    POST /api/ai/chat/feedback   {session_id, message_id, helpful}   (aggregate counters only)
    POST /api/ai/chat/close      destroy the chat (called by the X button)

All responses carry Cache-Control: no-store so a browser never keeps or replays a chat.
Route handlers are plain `def`, so FastAPI runs them in its thread pool and a slow model call
never blocks the game.
"""
import logging
from dataclasses import dataclass

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .config import load_dotenv_once
from .privacy import TurnTracker
from .service import ChatService
from .sessions import ChatError

log = logging.getLogger("camorra.chat")
NO_STORE = {"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"}
UNEXPECTED = ("The AI Companion ran into an unexpected problem. Please close the chat and open it again. "
              "The game itself is not affected.")


class SessionRequest(BaseModel):
    session_id: str = Field("", max_length=200)


class ChatRequest(BaseModel):
    session_id: str = Field("", max_length=200)
    message: str = Field("", max_length=4000)      # the service enforces the real (smaller) limit
    style: str = Field("friendly", max_length=24)  # answer style; unknown values fall back to the default


class FeedbackRequest(BaseModel):
    session_id: str = Field("", max_length=200)
    message_id: int
    helpful: bool


PUBLIC_FIELDS = ("reply", "message_id", "session_id", "styles", "default_style", "available", "message")


def _public(payload):
    """Players get the answer and what the page needs. Internals (answer mode, sources, evidence ids, model) stay server-side."""
    return {k: v for k, v in payload.items() if k in PUBLIC_FIELDS}


def _reply(payload, status=200):
    return JSONResponse(payload, status_code=status, headers=NO_STORE)


def _error(exc):
    return _reply({"detail": {"code": exc.code, "message": exc.message}}, exc.status_code)


def _guarded(action):
    """Run a chat action. Expected problems become clean 4xx answers; anything unexpected is
    logged (with its traceback, in the server console) and becomes a friendly 500 JSON answer, so
    the browser never receives a raw crash and the game keeps running."""
    try:
        return _reply(action())
    except ChatError as exc:
        return _error(exc)
    except Exception:
        log.exception("Unexpected error in the AI Companion")
        return _reply({"detail": {"code": "server_error", "message": UNEXPECTED}}, 500)


@dataclass
class ChatRuntime:
    router: object
    tracker: TurnTracker
    service: ChatService


def build_chat(get_game_state, service=None):
    load_dotenv_once()
    tracker = TurnTracker()
    service = service or ChatService(get_game_state, tracker)
    router = APIRouter()

    @router.get("/api/ai/chat/status")
    def chat_status():
        return _guarded(service.status)

    @router.get("/api/dev/chat-diagnostics")
    def chat_diagnostics(x_camorra_dev_token: str = Header(default="")):
        """Developer-only. 404 unless CAMORRA_DEV_TOKEN is set AND the request carries it. Never used by the game UI."""
        import hmac, os
        token = os.environ.get("CAMORRA_DEV_TOKEN", "")
        if not token or not hmac.compare_digest(token.encode(), x_camorra_dev_token.encode()):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        st = service.settings
        return {"mode": service.mode, "mode_reason": st.mode_reason, "model": st.model if service.mode == "llm" else None, "scope": st.scope}

    @router.post("/api/ai/chat/session")
    def chat_open(_: SessionRequest = None):
        return _guarded(lambda: _public(service.open_session()))

    @router.post("/api/ai/chat")
    def chat_message(request: ChatRequest):
        return _guarded(lambda: _public(service.handle_message(request.session_id, request.message, request.style)))

    @router.post("/api/ai/chat/feedback")
    def chat_feedback(request: FeedbackRequest):
        return _guarded(lambda: service.feedback(request.session_id, request.message_id, request.helpful))

    @router.post("/api/ai/chat/close")
    def chat_close(request: SessionRequest):
        def close():
            service.close_session(request.session_id)
            return {"closed": True}
        return _guarded(close)

    return ChatRuntime(router, tracker, service)


class TurnTrackerMiddleware:
    """Pure ASGI pass-through. After a game POST has been fully answered it tells the tracker
    that e.g. "SHOW MY ROLE" or "I'M READY" happened. It never reads a request body, never
    changes a response, and swallows its own errors, so it cannot affect the game."""

    def __init__(self, app, tracker, get_state):
        self.app, self.tracker, self.get_state = app, tracker, get_state

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] != "http" or scope.get("method") != "POST" or not path.startswith("/api/"):
            await self.app(scope, receive, send)
            return
        status = {"code": 0}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status["code"] = message.get("status", 0)
            await send(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                try:
                    self.tracker.observe(path, status["code"], self.get_state())
                except Exception:
                    pass

        await self.app(scope, receive, send_wrapper)
