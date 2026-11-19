# Conversation fix report (developer document)

## Root causes
1. **Retrieval ran on every message.** "i am talking to you" matched the discussion phase; "what can i cook now" matched the Doctor passage. Fix: `chatbot/conversation.py` decides greeting / small talk / stop / frustration / history / language / identity BEFORE any retrieval; non-game messages get a friendly redirect instead of retrieval.
2. **Topic memory leaked.** Short messages counted as follow-ups. Fix: a follow-up needs a real cue (why, explain more, what about, give an example, aur agar ...) or an active topic with a short message. Stop, frustration and off-topic replies clear the topic.
3. **Over-eager spelling correction** ("saying" -> "saving"). Common English words are now protected.
4. **User history confused with claims.** "did I say I am a doctor?" is answered from what the player actually stated; a question is never treated as a claim.
5. **Developer information in player text.** Replies, the public API, the status route and the chat widget exposed mode, sources, model, "Answer style", "Based on". All removed. `ChatService` also applies an output guard that replaces any reply containing internals. Technical reasons go to the server log only.
6. **Sticky language** is set only by an instruction ("speak Urdu"), not by a question about ability.

## Developer-only diagnostics
`GET /api/dev/chat-diagnostics` with header `X-Camorra-Dev-Token`. Returns 404 unless `CAMORRA_DEV_TOKEN` is set and matches (constant-time compare).

## Provider failure behaviour
In model mode a failed request shows: "Sorry, I couldn't process that just now. Please try again." The reason is logged server-side. Without a configured model, non-game requests get a game-only redirect.

## Honest status
- **Live LLM integration was NOT verified.** This environment has no API key and no network access to a provider. All model tests use MOCKED stubs and are labelled as such. The adapter targets any OpenAI-compatible endpoint (e.g. Groq, Gemini's OpenAI-compatible URL, OpenRouter); provider details came from a third-party article and were not checked against vendor docs.
- Dependency vulnerability scan (pip-audit) not run (no package index). Real FastAPI was not installed here; tests used a local shim.
- Browser check covered Chromium only.
- Tests: 220 Python tests (includes ~160 table-driven conversation cases plus multi-turn sequences, leak and formatting checks), 17 chat UI tests, 22 sound tests, 25 rule checks, and a 208-case benchmark (100% overall, privacy, safety, consistency; offline deterministic).
