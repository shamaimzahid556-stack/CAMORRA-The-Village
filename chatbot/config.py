"""Settings for the CAMORRA AI Companion. Everything comes from environment variables (or a
local `.env` file that is never shipped). API keys exist only on the server side."""
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

PROJECT_DIR = Path(__file__).resolve().parent.parent
KNOWLEDGE_DIR = PROJECT_DIR / "game_knowledge"
DATA_DIR = Path(os.environ.get("CAMORRA_DATA_DIR", PROJECT_DIR / "chatbot_data"))

log = logging.getLogger("camorra.chat")
_dotenv_loaded = False


def _read_env_text(env_file):
    """Read a .env file in whatever encoding Windows tools produced (UTF-8, UTF-8 with BOM,
    UTF-16 from PowerShell redirects). Returns "" if the file is missing or unreadable."""
    try:
        raw = env_file.read_bytes()
    except OSError:
        return ""
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        encodings = ("utf-16", "utf-8-sig", "latin-1")
    else:
        encodings = ("utf-8-sig", "utf-16", "latin-1")
    for enc in encodings:
        try:
            return raw.decode(enc)
        except UnicodeError:
            continue
    return ""


def _strip_inline_comment(value):
    """`20   # seconds` -> `20`. A '#' only starts a comment when it follows whitespace and the
    value is not quoted, so passwords and URLs containing '#' inside quotes keep working."""
    value = value.strip()
    if value[:1] in ("'", '"'):
        quote = value[0]
        close = value.find(quote, 1)
        if close != -1:
            return value[1:close]
        return value[1:]
    for i, ch in enumerate(value):
        if ch == "#" and (i == 0 or value[i - 1].isspace()):
            return value[:i].strip()
    return value


def load_dotenv_once(path=None):
    """Tiny .env reader (KEY=VALUE lines). Real environment variables always win. It never raises:
    a damaged or oddly encoded file simply contributes nothing."""
    global _dotenv_loaded
    if _dotenv_loaded and path is None:
        return
    _dotenv_loaded = True
    env_file = Path(path) if path else PROJECT_DIR / ".env"
    for raw in _read_env_text(env_file).splitlines():
        line = raw.strip().lstrip("\ufeff")
        if line.lower().startswith("export "):
            line = line[7:].strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key:
            os.environ.setdefault(key, _strip_inline_comment(value))


def _number(name, default, cast):
    """Read a numeric setting; a typo falls back to the default instead of stopping the game."""
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return cast(_strip_inline_comment(str(raw)))
    except (TypeError, ValueError):
        log.warning("Ignoring invalid value for %s; using %s", name, default)
        return default


def _clamped(name, default, cast, low, high):
    value = _number(name, default, cast)
    if not low <= value <= high:
        log.warning("Ignoring out-of-range value for %s; using %s", name, default)
        return default
    return value


@dataclass(frozen=True)
class Settings:
    llm_mode: str            # "auto" | "llm" | "offline"
    base_url: str
    api_key: str
    model: str
    timeout: float
    max_message_chars: int
    max_messages_per_session: int
    min_seconds_between_messages: float
    session_idle_seconds: int
    session_max_seconds: int
    history_messages: int
    metrics_enabled: bool
    scope: str = "game"                  # "game": CAMORRA topics only (default) | "general": also answer general tasks
    max_response_chars: int = 4000       # a model answer is cut here, whatever the provider's token limit
    max_retries: int = 2                 # extra attempts after a retryable provider error
    total_deadline: float = 30.0         # seconds for one model request including retries
    global_chat_per_minute: int = 90     # all chat messages and session openings together, across every session

    @property
    def is_local_endpoint(self):
        host = (urlparse(self.base_url).hostname or "").lower()
        return host in {"localhost", "127.0.0.1", "::1"}

    @property
    def is_openai(self):
        return (urlparse(self.base_url).hostname or "").lower() == "api.openai.com"

    @property
    def endpoint_problem(self):
        """Why the configured model endpoint is not acceptable, or None. Remote endpoints must use HTTPS (the API
        key travels in the request); plain HTTP is accepted only for a model on this computer. No credentials in the URL."""
        parts = urlparse(self.base_url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            return "CAMORRA_LLM_BASE_URL is not a valid http(s) URL."
        if parts.username or parts.password:
            return "CAMORRA_LLM_BASE_URL must not contain a user name or password."
        if parts.scheme != "https" and not self.is_local_endpoint:
            return "CAMORRA_LLM_BASE_URL must use https:// unless the model runs on this computer."
        return None

    @property
    def llm_configured(self):
        """A model is used only if a key or a local server is configured and the mode is not "offline".
        (Mode "llm" does not create a key: without one the companion stays in rulebook mode.)"""
        if self.llm_mode == "offline" or self.endpoint_problem:
            return False
        return bool(self.api_key) or self.is_local_endpoint


def _mode_reason(self):
    """Why the companion is (not) using a model, in words that are safe to show: never includes the key."""
    if self.llm_mode == "offline":
        return "forced_offline"
    if self.endpoint_problem:
        return "unsafe_endpoint"
    if self.api_key:
        return "api_key"
    if self.is_local_endpoint:
        return "local_model"
    return "no_api_key"


Settings.mode_reason = property(_mode_reason)


def load_settings():
    load_dotenv_once()
    env = os.environ.get

    def text(name, default=""):
        return _strip_inline_comment(env(name) or "") or default

    mode = text("CAMORRA_LLM_MODE", "auto").lower()
    if mode not in ("auto", "llm", "offline"):
        log.warning("Unknown CAMORRA_LLM_MODE %r; using auto", mode)
        mode = "auto"
    scope = text("CAMORRA_SCOPE", "game").lower()
    if scope not in ("game", "general"):
        log.warning("Unknown CAMORRA_SCOPE %r; using game", scope)
        scope = "game"
    key = text("CAMORRA_LLM_API_KEY") or text("OPENAI_API_KEY")
    return Settings(
        llm_mode=mode,
        base_url=(text("CAMORRA_LLM_BASE_URL") or "https://api.openai.com/v1").rstrip("/"),
        api_key=key,
        model=text("CAMORRA_LLM_MODEL") or "gpt-4o-mini",
        timeout=_number("CAMORRA_LLM_TIMEOUT", 20.0, float),
        max_message_chars=_number("CAMORRA_MAX_MESSAGE_CHARS", 500, int),
        max_messages_per_session=_number("CAMORRA_MAX_MESSAGES", 40, int),
        min_seconds_between_messages=_number("CAMORRA_MIN_SECONDS_BETWEEN_MESSAGES", 0.6, float),
        session_idle_seconds=_number("CAMORRA_SESSION_IDLE_SECONDS", 900, int),
        session_max_seconds=_number("CAMORRA_SESSION_MAX_SECONDS", 1800, int),
        history_messages=_number("CAMORRA_HISTORY_MESSAGES", 8, int),
        metrics_enabled=(text("CAMORRA_METRICS", "on").lower() != "off"),
        scope=scope,
        max_response_chars=_clamped("CAMORRA_MAX_RESPONSE_CHARS", 4000, int, 200, 20000),
        max_retries=_clamped("CAMORRA_LLM_RETRIES", 2, int, 0, 5),
        total_deadline=_clamped("CAMORRA_LLM_DEADLINE", 30.0, float, 1.0, 300.0),
        global_chat_per_minute=_clamped("CAMORRA_GLOBAL_CHAT_PER_MINUTE", 90, int, 1, 10000),
    )


def validate_settings(settings):
    """Startup validation. Returns a list of human-readable problems (empty = fine). Unsafe values are never used:
    a bad endpoint turns the model off instead of sending a key somewhere unsafe."""
    problems = []
    if settings.endpoint_problem:
        problems.append(settings.endpoint_problem + " The AI model is switched off until this is fixed.")
    if settings.timeout <= 0 or settings.timeout > 120:
        problems.append("CAMORRA_LLM_TIMEOUT should be between 1 and 120 seconds.")
    if settings.llm_mode == "llm" and not settings.llm_configured and not settings.endpoint_problem:
        problems.append("CAMORRA_LLM_MODE=llm but no API key or local model is configured; running in rulebook mode.")
    return problems
