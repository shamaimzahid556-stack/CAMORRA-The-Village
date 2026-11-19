"""Production-style launcher: sets up rotating log files, validates the configuration, then starts uvicorn.

    python serve.py                      # 127.0.0.1:8000 (this computer only)
    CAMORRA_HOST=0.0.0.0 CAMORRA_ALLOW_REMOTE=1 python serve.py     # deliberately reachable from other devices (see DEPLOYMENT.md)

Logs never contain API keys, chat messages, player names, roles or other private game information: only event names,
status codes and error types."""
import logging
import logging.handlers
import os
import sys

from chatbot import config


def setup_logging():
    level = getattr(logging, os.environ.get("CAMORRA_LOG_LEVEL", "INFO").upper(), logging.INFO)
    log_dir = config.DATA_DIR / "logs"
    handlers = [logging.StreamHandler(sys.stderr)]
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.handlers.RotatingFileHandler(log_dir / "camorra.log", maxBytes=1_000_000, backupCount=5,
                                                             encoding="utf-8"))            # about 6 MB at most, oldest deleted
    except OSError as exc:
        print(f"Warning: file logging disabled ({exc.__class__.__name__}).", file=sys.stderr)
    logging.basicConfig(level=level, handlers=handlers, force=True,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")


def main():
    setup_logging()
    log = logging.getLogger("camorra.startup")
    config.load_dotenv_once()
    settings = config.load_settings()
    for problem in config.validate_settings(settings):
        log.warning("Configuration: %s", problem)
    log.info("AI mode: %s (reason: %s); scope: %s", "llm" if settings.llm_configured else "offline", settings.mode_reason, settings.scope)
    import uvicorn
    uvicorn.run("app:app", host=os.environ.get("CAMORRA_HOST", "127.0.0.1"), port=int(os.environ.get("CAMORRA_PORT", "8000")),
                log_level=os.environ.get("CAMORRA_LOG_LEVEL", "info").lower(), proxy_headers=False, server_header=False)


if __name__ == "__main__":
    main()
