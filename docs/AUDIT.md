# Audit summary (this release)

Classification: CONFIRMED (real, fixed) / ALREADY FIXED / PARTIALLY FIXED / NOT APPLICABLE / NEEDS INVESTIGATION.

| Area | Finding | Status | Evidence |
|---|---|---|---|
| New Game | Button only reloaded; finished game and chat sessions stayed on the server | CONFIRMED, fixed | `tests/test_new_game.py` |
| Chatbot runtime depends on `ai_lab/` | `chatbot` imported `ai_lab.nlp` | CONFIRMED, fixed: moved to `shared/nlp.py`, `ai_lab/nlp.py` re-exports | import tests, full suite |
| Request size | No limit | CONFIRMED, fixed: 64 KB ASGI limit (413) | `tests/test_security_and_config.py` |
| CSP | No Content-Security-Policy | CONFIRMED, fixed; the one inline handler is allowed by hash; test checks the page has no other inline script/handler | same |
| Model endpoint | http:// remote accepted | CONFIRMED, fixed: https required for non-local, creds-in-URL refused | same |
| Retries/timeouts | single attempt, unbounded body | CONFIRMED, fixed: bounded retries, backoff, deadline, 256 KB / answer-length caps | same |
| Chat rate limit | per-session only | CONFIRMED, fixed: global sliding window incl. session creation | same |
| Provider exceptions | unexpected exception type could escape | CONFIRMED, fixed | `test_provider_bug_does_not_crash_the_chat` |
| Health/readiness | none | CONFIRMED, fixed (`/healthz`, `/readyz`) | `Health` test |
| Logging | no rotation, no security events | CONFIRMED, fixed in `serve.py` | manual |
| Player identity | No login; client IDs not proof of identity | PARTIALLY FIXED: server verifies the device handover (I'M READY) for private data; app stays local-only; not a multi-user auth system | README / DEPLOYMENT |
| Persistence | state lost on restart | ALREADY DECIDED: documented, intentional | DEPLOYMENT |
| `chatbot_data/metrics.json` | stale runtime data shipped | CONFIRMED, removed; dir auto-created (`/readyz` creates it) | file tree |
| `static/role-assignment-background-13.png` | byte-identical duplicate of #8, excluded in `game.js` | CONFIRMED duplicate; moved to `archive/` (not deleted). Never requested by the page | `cmp`, game.js L17 |
| `unused_assets/`, `assets_backup/` | referenced by nothing | CONFIRMED unused; kept under `archive/` | grep |
| `ai_lab/`, `AI_LAB_README.md`, `run_ai_lab.py` | academic material | ALREADY FINE: preserved; excluded from the production package | DEPLOYMENT |
| Dependency scan | not runnable offline | NEEDS INVESTIGATION: runs in CI | DEPLOYMENT |
| Cross-browser, mobile | tested in Chromium only | PARTIALLY: other browsers untested | README |
