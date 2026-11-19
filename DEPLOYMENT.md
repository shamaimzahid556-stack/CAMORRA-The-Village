# CAMORRA deployment guide

## What this application is (and is not)
CAMORRA is a **pass-the-device party game**: one browser on one shared device. It has **no accounts and no per-player
login**, and the game state lives in one server process. It is therefore supported as a **local / single-table** app.
Public internet deployment is **not** presented as secure multi-user hosting: anyone who can reach the server can use the
single game. By default the server only answers requests from this computer (`LocalOnlyMiddleware`). If you deliberately
expose it (for example on a home network or behind a reverse proxy), put authentication in front of it (reverse-proxy basic
auth, VPN, or an identity-aware proxy) and keep one game per instance.

## Install
```
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt            # reproducible: pip-compile --generate-hashes (see Dependencies)
cp .env.example .env                       # optional: AI settings
```

## Run
Local: `python serve.py` (127.0.0.1:8000) or `uvicorn app:app`.
Production-style: `python serve.py` (rotating logs in `chatbot_data/logs/`, config validation at start) behind a reverse
proxy. Example nginx (HTTPS terminates here; the body limit mirrors the app's 64 KB limit):
```
server {
  listen 443 ssl http2;  server_name camorra.example.com;
  # ssl_certificate ... ssl_certificate_key ...
  client_max_body_size 64k;
  location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_read_timeout 60s;
  }
  limit_req_zone $binary_remote_addr zone=camorra:10m rate=20r/s;   # place in http{}; then: limit_req zone=camorra burst=40;
}
```
Set `CAMORRA_HSTS=1` when served over HTTPS. If the proxy is not on the same machine, the app's local-only guard must be
relaxed deliberately (see `LocalOnlyMiddleware` in `app.py`); read its comment first.

## AI provider
Provider-independent: any OpenAI-compatible `/chat/completions` endpoint. Variables: `OPENAI_API_KEY` or
`CAMORRA_LLM_API_KEY`, `CAMORRA_LLM_BASE_URL`, `CAMORRA_LLM_MODEL`, `CAMORRA_LLM_MODE` (`auto|llm|offline`),
`CAMORRA_LLM_TIMEOUT`, `CAMORRA_LLM_RETRIES`, `CAMORRA_LLM_DEADLINE`, `CAMORRA_MAX_RESPONSE_CHARS`, `CAMORRA_SCOPE`.
Rules enforced in code: remote endpoints must be `https://` (otherwise the model is switched off and the key is never sent),
no credentials inside the URL, redirects are not followed, provider replies are capped at 256 KB and answers at
`CAMORRA_MAX_RESPONSE_CHARS`, retries only for timeouts/429/5xx with exponential backoff inside a total deadline.
The key is read server-side only and never reaches the browser or the logs.

Free-tier options reported by a third-party article dated 2026-10-22 (**not verified against the providers' pages and not
live-tested by this project**; limits and data-use terms change, check them before relying on them):
| Provider | Base URL | Reported free limits | Caveat |
|---|---|---|---|
| Groq | `https://api.groq.com/openai/v1` | e.g. 30 requests/min, 1K requests/day, 8K tokens/min for `openai/gpt-oss-20b` | token-per-minute cap is hit first |
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai/` | free tier, limits shown in AI Studio | free-tier content may be used to improve Google products and read by reviewers: use it only knowing that |
| OpenRouter | `https://openrouter.ai/api/v1` | `:free` models, 20 req/min and 50/day under 10 credits | free model list rotates |
OpenAI's own API is paid. A local model (Ollama, LM Studio: `http://localhost:11434/v1`) costs nothing and sends no data out.
What the model is sent: the player's message, a few rulebook excerpts, the recent chat, and only that player's *authorized
evidence* (see README). Hidden roles and other players' secrets never enter the prompt.

## Health checks
`GET /healthz` -> `{"status":"ok"}` (liveness). `GET /readyz` -> 200/503 with three booleans (static files, rulebook, data
dir writable). `GET /api/ai/chat/status` -> AI mode/reason/scope. None of them reveals game state, names, roles or keys.

## State recovery and persistence
Chosen strategy: **no database**. A refresh resumes the current screen from the server (`/api/state`); a server restart ends
the game (it is a short party game, and storing roles on disk would add a secret-at-rest risk). Chat sessions are
memory-only and wiped on idle, on game reset and on NEW GAME. Runtime data (aggregate help counters, logs) is under
`chatbot_data/` and is created automatically; it is not part of the release and holds no chat text or game secrets.
Backup: nothing to back up except your `.env`; `chatbot_data/` is disposable.

## Logging
`serve.py` writes `chatbot_data/logs/camorra.log` (1 MB x 5 rotated files, oldest deleted). Security events log the category
only (for example `security_event kind=injection`), never the message, names, roles or keys.

## API versioning
The browser client and API ship together; endpoints are unversioned `/api/...`. Breaking changes must add `/api/v2/...`
alongside. The error body is always `{"detail": ...}`.

## Updating
Stop the server, replace the files (keep `.env`), `pip install -r requirements.txt`, run `python -m unittest discover -s tests`,
start again. The `?v=` query on static files in `index.html` busts browser caches.

## Dependencies
`requirements.txt` uses compatible-release ranges. A vulnerability scan (`pip-audit -r requirements.txt`) runs in CI
(`.github/workflows/ci.yml`). It could **not** be run while preparing this release (no package index access), so no scan result
is claimed.

## Release package
Production package = everything except `tests/`, `evaluation/`, `archive/`, `.github/`, `ai_lab/` academic material and
`AI_LAB_README.md`/`run_ai_lab.py` if you do not need them. `shared/` (NLP used by the chatbot at runtime) and `game_knowledge/`
**must** ship.
