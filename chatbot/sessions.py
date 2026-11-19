"""Temporary private chat sessions. Everything lives in server memory only.

* A session is created when a player opens the chat and destroyed when they close it (X button),
  when it expires, or when the game's turn changes (the session is bound to a turn key).
* Opening a new chat destroys every other session first: on a shared device only one private
  chat can exist at a time.
* Session ids are unguessable random tokens. The browser keeps the id in a JavaScript variable
  only (never in localStorage / sessionStorage / cookies).
* Nothing here is ever written to disk.
"""
import secrets
import threading
import time
from dataclasses import dataclass, field


class ChatError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message, code=None, status_code=None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code


class ChatUnavailable(ChatError):
    status_code, code = 403, "unavailable"


class SessionExpired(ChatError):
    status_code, code = 410, "session_expired"


class RateLimited(ChatError):
    status_code, code = 429, "rate_limited"


@dataclass
class ChatSession:
    id: str
    turn_key: str
    created: float
    last_active: float
    history: list = field(default_factory=list)       # [(role, text)] for this session only
    memory: dict = field(default_factory=dict)        # follow-up focus (roles, phase, topics)
    replies: dict = field(default_factory=dict)       # message_id -> {"chunks": [...], "intent": str}
    message_count: int = 0
    last_message_at: float = float("-inf")     # "never": the first message is never rate-limited
    in_flight: bool = False
    next_message_id: int = 1


class SessionStore:
    def __init__(self, idle_seconds=900, max_seconds=1800, clock=time.monotonic):
        self._sessions = {}
        self._lock = threading.RLock()
        self.idle_seconds, self.max_seconds, self._clock = idle_seconds, max_seconds, clock

    def _destroy(self, session):
        """Drop the session and overwrite what it held, so nothing lingers in memory."""
        session.history.clear()
        session.memory.clear()
        session.replies.clear()
        self._sessions.pop(session.id, None)

    def open(self, turn_key):
        with self._lock:
            for s in list(self._sessions.values()):     # one private chat at a time
                self._destroy(s)
            now = self._clock()
            session = ChatSession(secrets.token_urlsafe(24), turn_key, now, now)
            self._sessions[session.id] = session
            return session

    def get(self, session_id, turn_key):
        """Return the live session, or raise SessionExpired. A session is valid only for the
        turn it was opened on."""
        with self._lock:
            session = self._sessions.get(session_id or "")
            if session is None:
                raise SessionExpired("This chat has ended. A fresh private chat will start when you reopen it.")
            now = self._clock()
            if now - session.last_active > self.idle_seconds or now - session.created > self.max_seconds:
                self._destroy(session)
                raise SessionExpired("This chat timed out and was cleared.")
            if session.turn_key != turn_key:
                self._destroy(session)
                raise SessionExpired("The game moved on to a different screen or player, so this chat was cleared.",
                                     code="turn_changed")
            session.last_active = now
            return session

    def is_active(self, session_id):
        with self._lock:
            return session_id in self._sessions

    def close(self, session_id):
        """Idempotent: closing an unknown or already-closed session is not an error."""
        with self._lock:
            session = self._sessions.get(session_id or "")
            if session is not None:
                self._destroy(session)

    def close_all(self):
        with self._lock:
            for s in list(self._sessions.values()):
                self._destroy(s)

    def count(self):
        with self._lock:
            return len(self._sessions)
