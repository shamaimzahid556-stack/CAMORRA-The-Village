# Chatbot evaluation

## What was measured
`python -m evaluation.benchmark` drives the **real chatbot service** (not the HTTP layer) on a fixed fictional table
(Ali Detective, Sara Doctor, Omar and Hina Mafia, three Villagers; the asker is Ali on a verified night turn), **offline**
(no model, no network), twice per case. A case passes when every `has` regex matches, no `lacks` regex matches, any length
limit holds, and no player is tied to a hidden role. Criteria reported: overall, privacy (injection / hidden-info /
unauthorized cases), safety (no role statement in any reply), consistency (same answer on both runs).
Targets: overall >= 90 %, privacy = safety = consistency = 100 %. `tests/test_benchmark.py` fails the build below them.

## Results (this release)
| Set | Cases | First run | Final |
|---|---|---|---|
| Main benchmark (`evaluation/cases.py`) | 208 across 24 categories; English 175, Roman Urdu 18, Urdu script 9, mixed 6 | 90.4 % (privacy 90.3 %) | 100 % (privacy, safety, consistency 100 %) |
| Held-out (`evaluation/holdout.py`, written after tuning, run once) | 32 | **84.4 %** | 93.8 % after fixing the generalisable gaps it exposed (it is no longer held out) |
| Rulebook retrieval (`chatbot/evaluation.py`) | 101 questions | | top-1 85.1 %, top-3 99.0 % |

## How to read this honestly
* The main benchmark was used while fixing the chatbot, so its 100 % is a **regression suite**, not an independent
  accuracy estimate. The fairest generalisation number is the held-out **first run: 84.4 %** (27 of 32). The privacy
  and safety criteria were 100 % on that first run.
* Expectations are regexes on meaning (for example "mentions investigating"), not exact strings; they can still be fooled
  by an answer that contains the right words in the wrong sentence. Naturalness is **not** scored automatically.
* Offline mode answers Roman Urdu / Urdu questions **in English** (it understands them via a keyword lexicon). Native
  Roman Urdu *replies* need a configured model; that path is covered only by tests that check what the model is **sent**
  (language instruction, original message, no hidden data), using a recording stand-in. **No live provider was called, so
  live answer quality, live Roman Urdu quality and provider behaviour are untested.**
* Known remaining miss: "Is there a limit on Mafia count?" retrieves the Mafia role section instead of the player-count
  section (the answer exists in the rulebook; retrieval ranks it lower).
* No claim is made that this chatbot is comparable to ChatGPT or DeepSeek; no comparative evaluation was run.

## Non-interference check
`tests/test_chat_fairness.py` changes only the hidden facts the asker may not know (other players' roles) and requires
identical replies and evidence; it passes for every asker role.
