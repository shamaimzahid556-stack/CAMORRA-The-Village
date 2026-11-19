# AI subject topics in CAMORRA

You kept four AI-subject topics. This file says exactly where each one is, what it does, and what
is (and is not) real, so you can explain it honestly.

| Topic | File | What it does in this project |
|---|---|---|
| **Backtracking** | `ai_lab/backtracking.py` | A generic backtracking solver with the "minimum remaining values" trick, plus 8-Queens (92 solutions). |
| **CSP** (Constraint Satisfaction) | `ai_lab/csp.py` | CAMORRA-themed CSPs solved with that backtracking solver: role assignment (exact role counts + "no two Mafia seated side by side"), checking that dealt roles obey the game's counts, and scheduling the phases of a day into ordered time slots. |
| **Hill Climbing** | `ai_lab/hillclimb.py` | Simple, steepest-ascent and stochastic hill climbing on a table-seating puzzle and on a maze (where all three get stuck in a local maximum). |
| **NLP** | `ai_lab/nlp.py` + `chatbot/` | The text-processing core of the AI Companion chatbot (below). |

Run the study demo: `python run_ai_lab.py` (or `csp`, `backtracking`, `hillclimb`, `nlp "your sentence"`).

**Note:** CSP, backtracking and hill climbing are standalone, tested study modules. The
game itself does not call them while playing (its role dealing is a plain random shuffle, deliberately kept simple). NLP is the one topic used by a live feature, the chatbot.

## NLP: what is explicit code, what is the language model

The chatbot answers in three layers. Do not mix them up in a presentation:

| Layer | Who does it | Where |
|---|---|---|
| **Explicit NLP written in this project (Python, standard library only)** | our code | `ai_lab/nlp.py`, `chatbot/understanding.py`, `chatbot/retrieval.py` |
| **Semantic retrieval of the right rulebook sections** | our code (TF-IDF, not neural embeddings) | `chatbot/retrieval.py` |
| **Writing the final natural sentence** | an external language model *if you configure one*; otherwise our offline composer, which only re-uses verified rulebook sentences | `chatbot/llm.py`, `chatbot/responder.py` |

Explicit NLP techniques that really exist in the code:

1. **Tokenization + contraction expansion** ("can't" -> "can not", "what's" -> "what is").
2. **Lemmatization** ("voted" -> "vote", "was" -> "be", "investigating" -> "investigate"), dictionary plus suffix rules. Stemming (`stem()`) is also implemented for comparison, but the chatbot matches on lemmas.
3. **Spelling tolerance** with Damerau-Levenshtein edit distance, deliberately conservative ("docter" -> "doctor", but real words are never changed).
4. **Named-entity recognition** with a gazetteer: roles (and their synonyms: *investigator* = Detective, *killer* = Mafia, *medic* = Doctor), phases, actions, game mechanics, button names.
5. **Intent recognition** with weighted cues + entities (role question, night guidance, voting, win condition, interface, troubleshooting, strategy, "what should I do now", greeting, ...). It routes and prioritises; it does not limit what can be asked.
6. **Bag of words / TF-IDF + cosine similarity** over the rulebook, with a character-trigram view that survives typos.
7. **Follow-up resolution**: "When can I use it?" inherits the role from the previous turn; "I still don't understand" re-explains the previous section in its simpler wording. This memory lives only inside one private chat session.

Not claimed: there are no neural embeddings, no trained classifier and no sentiment analysis.

How good is retrieval? `python -m chatbot.improve eval` runs 95 differently-worded test questions
(typos, synonyms, follow-ups). Measured: the right section is ranked first for 84% and in the top
three for 99%. These questions are only a test set. The chatbot never looks questions up in it.

## Files removed from `ai_lab/` and why that was safe

Removed: `adversarial.py`, `analysis.py`, `api.py`, `labs.py`, `ml.py`, `recorder.py`, `search.py`,
`town.py`, `ui.html`. Before deleting I searched every import and route: only `app.py` imported
`ai_lab.api` and `ai_lab.recorder`; nothing in `game/` or `static/` referenced `ai_lab`; the four
kept modules do not import any removed one. `app.py` now imports the chatbot instead, `run_ai_lab.py`
was rewritten for the four topics, and a test (`tests/test_subject_modules.py`) fails if anything
ever references a removed module again.
`nlp.py` was rewritten (the old demo-only functions are gone; the useful functions were kept and
extended). `csp.py` lost nothing: its solver and N-Queens moved to the new `backtracking.py` and
are re-exported.

## Privacy and "learning"

See `README.md` ("AI Companion" section) for the privacy design and the improvement workflow.
