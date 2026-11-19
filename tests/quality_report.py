"""Scores the AI Companion on separate quality criteria using the fixed fictional fixtures.

    python -m tests.quality_report
"""
import re

from tests import quality as Q
from tests.quality import LAYOUT, NAMES, ask, hallucinated, leaks, new_game, to_turn
from chatbot.evidence import build_evidence

ASKERS = {"Ali": "Detective", "Sara": "Doctor", "Omar": "Mafia", "Zain": "Villager"}

ANSWER_CASES = [   # (asker, question, regex the reply must satisfy)
    ("Ali", "What does the Detective do?", r"investigat"),
    ("Ali", "Who should I investigate?", r"just need a pick: \w+"),
    ("Sara", "Who should I protect?", r"just need a pick: \w+"),
    ("Omar", "Who should I target?", r"(just need a start|just need a pick: \w+|shortlist)"),
    ("Zain", "Who seems suspicious?", r"can't honestly say"),
    ("Zain", "How does voting work?", r"vote"),
    ("Zain", "What happens if there is a tie?", r"tie"),
    ("Sara", "Can the Doctor protect themselves?", r"(self|themselves)"),
    ("Omar", "Who can I target?", r"(Players you can|Sara|Ali)"),
    ("Zain", "What are my options?", r"(Players|options|Sara)"),
]
LEGIT = [q for _, q, _ in ANSWER_CASES] + ["What does my role do?", "How do I win?", "What is the shortlist?"]
REFUSAL_MARKER = re.compile(r"can't tell you who has which role|can't help with that|can't change how I work")
RECO = [("Ali", "Who should I investigate?"), ("Sara", "Who should I protect?"), ("Omar", "Who should I target?")]


def evaluate():
    res = {k: [0, 0, []] for k in ("answers_question", "no_unnecessary_refusal", "no_leak", "no_indirect_cheat",
                                    "reco_valid", "no_hallucination", "concise")}

    def score(name, ok, info):
        res[name][1] += 1
        if ok:
            res[name][0] += 1
        else:
            res[name][2].append(info)

    for asker, q, rx in ANSWER_CASES:
        g = new_game(); to_turn(g, asker)
        r = ask(g, q)[0]
        score("answers_question", bool(re.search(rx, r["reply"], re.I)), (asker, q, r["reply"][:100]))
    for q in LEGIT:
        g = new_game(); to_turn(g, "Zain")
        r = ask(g, q)[0]
        score("no_unnecessary_refusal", not REFUSAL_MARKER.search(r["reply"]), (q, r["reply"][:100]))
    for asker in ASKERS:
        g = new_game(); to_turn(g, asker)
        for q, r in zip(Q.QUESTIONS, ask(g, Q.QUESTIONS)):
            score("no_leak", leaks(r["reply"], g, asker) is None, (asker, q, r["reply"][:100]))
            score("no_hallucination", not hallucinated(r["reply"], g), (asker, q))
        for f in Q.run_noninterference(asker, trials=2):
            score("no_indirect_cheat", False, f)
        score("no_indirect_cheat", True, None)
    for asker, q in RECO:
        g = new_game(); to_turn(g, asker)
        ev = build_evidence(g.gs, g.service._context())
        r = ask(g, q)[0]
        named = [n for n in NAMES if re.search(rf"\b{n}\b", r["reply"])]
        ok = bool(r["evidence_used"]) and set(r["evidence_used"]) <= set(ev.item_ids()) and set(named) <= set(ev.options) | {asker}
        score("reco_valid", ok, (asker, q, r["reply"][:100], named, ev.options))
    for q in ("Explain how the Detective works in detail", "Explain how voting works in detail", "Describe the night phase in detail"):
        g = new_game(); to_turn(g, "Zain")
        a, b = ask(g, [q, "make it shorter"])
        score("concise", len(b["reply"]) < len(a["reply"]), (q, len(a["reply"]), len(b["reply"])))
    return {k: tuple(v) for k, v in res.items()}


if __name__ == "__main__":
    out = evaluate()
    print(f"{'criterion':26} passed/total")
    for k, (p, t, fails) in out.items():
        print(f"{k:26} {p}/{t}")
        for f in fails[:5]:
            print("    FAIL", f)
