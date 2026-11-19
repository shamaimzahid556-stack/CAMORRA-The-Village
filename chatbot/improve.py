"""Safe, human-approved improvement of the AI Companion's explanations.

What "learning" means in CAMORRA (and what it does not):
  * The language model's weights are NEVER changed. Nothing is retrained or fine-tuned.
  * The assistant improves by getting better *simple explanations* in the knowledge base.
  * Evidence comes only from aggregate counters (chatbot/metrics.py): which rulebook sections are
    often rated "not helpful" or are followed by "I still don't understand".
  * Drafts are written from the canonical rulebook text, never from anyone's chat.
  * A draft must pass automatic checks (no new numbers/buttons/roles, no links, retrieval quality
    not worse, no secret-extraction patterns) AND be approved by a human with --yes.
  * Approved text can only replace a section's "simple explanation". Rules text is changed only
    by editing game_knowledge/*.md by hand, then running chatbot.verify_rules.

Commands (run from the project folder):
    python -m chatbot.improve report [--min 5]
    python -m chatbot.improve propose <section-id>
    python -m chatbot.improve check game_knowledge/proposals/<file>.md
    python -m chatbot.improve approve game_knowledge/proposals/<file>.md --yes
    python -m chatbot.improve eval
"""
import argparse
import re
import sys
from pathlib import Path

from shared.nlp import tokenize

from . import llm
from .config import KNOWLEDGE_DIR, load_settings
from .engine import Engine
from .evaluation import run_eval
from .knowledge import load_knowledge
from .metrics import Metrics
from .responder import sentences

PROPOSALS = KNOWLEDGE_DIR / "proposals"
APPROVED = KNOWLEDGE_DIR / "approved"
NUMBER_WORDS = "one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen".split()


# ---------------------------------------------------------------------------------------------
def weak_sections(snapshot, min_samples=5):
    rows = []
    for sid, m in snapshot.get("sections", {}).items():
        asked, rated = m.get("asked", 0), m.get("helpful", 0) + m.get("unhelpful", 0)
        if asked < min_samples:
            continue
        unhelpful = m["unhelpful"] / rated if rated >= 3 else 0.0
        confused = m["confused"] / asked
        score = max(unhelpful, confused)
        rows.append({"id": sid, "asked": asked, "unhelpful_rate": unhelpful, "confusion_rate": confused,
                     "needs_work": score >= 0.25})
    return sorted(rows, key=lambda r: -max(r["unhelpful_rate"], r["confusion_rate"]))


def draft_simple_explanation(chunk, settings):
    """A first draft for a human to edit. Uses only the canonical section text as input."""
    if settings.llm_configured:
        try:
            msgs = [{"role": "system", "content": "Rewrite the rule text for a complete beginner in at most 4 short sentences. "
                     "Use ONLY facts that are in the text. Do not add numbers, buttons, roles or rules that are not in it."},
                    {"role": "user", "content": f"{chunk.title}\n\n{chunk.text}"}]
            return llm.complete(settings, msgs, max_tokens=250), "llm"
        except llm.LLMError as exc:
            print(f"(model unavailable: {exc}; writing an offline draft)")
    base = chunk.simple or " ".join(sentences(chunk.text)[:2])
    return base, "offline"


def check_proposal(chunk, text, engine):
    """Return (passed, [messages])."""
    problems, notes = [], []
    if not 20 <= len(text) <= 600:
        problems.append("Length must be between 20 and 600 characters.")
    if len(sentences(text)) > 6:
        problems.append("Use at most 6 sentences.")
    canonical = f"{chunk.title} {chunk.text} {chunk.simple}"
    canon_numbers = set(re.findall(r"\d+", canonical)) | {w for w in NUMBER_WORDS if re.search(rf"\b{w}\b", canonical.lower())}
    for n in set(re.findall(r"\d+", text)):
        if n not in canon_numbers:
            problems.append(f"Introduces the number {n}, which is not in the verified text.")
    for w in NUMBER_WORDS:
        if re.search(rf"\b{w}\b", text.lower()) and w not in canon_numbers and w != "one":
            problems.append(f"Introduces the number word '{w}', which is not in the verified text.")
    buttons = set(engine.kb.facts.get("buttons", []))
    for caps in re.findall(r"\b[A-Z][A-Z' &]{3,}\b", text):
        caps = caps.strip()
        if caps not in buttons and caps not in canonical:
            problems.append(f"Mentions '{caps}', which is not a known button or term.")
    known_roles = set(engine.kb.facts["roles"])
    for role in re.findall(r"\b(Mafia|Detective|Doctor|Villager|Sheriff|Medic|Seer|Werewolf|Jester)\b", text):
        if role not in known_roles:
            problems.append(f"Mentions a role that does not exist in CAMORRA: {role}.")
    if re.search(r"https?://|www\.|@\w+\.\w+|<\s*script|api[_ ]?key|password", text, re.I):
        problems.append("Contains a link, address or credential-like text.")
    from .privacy import detect_secret_request
    category = detect_secret_request(text, ())
    if category:
        problems.append(f"Contains wording that looks like an attempt to extract secrets or override the rules ({category}).")
    canon_lemmas = set(tokenize(canonical))
    novel = [t for t in set(tokenize(text)) if t not in canon_lemmas and len(t) > 4]
    if len(novel) > max(6, 0.35 * len(set(tokenize(text)))):
        notes.append("Many words are not in the verified text; please re-read it for added claims: " + ", ".join(sorted(novel)[:10]))

    before = run_eval(engine)
    old = (chunk.simple, chunk.approved_simple)
    chunk.simple, chunk.approved_simple = text, True
    try:
        engine2 = Engine(engine.kb)          # re-index with the proposal applied
        after = run_eval(engine2)
    finally:
        chunk.simple, chunk.approved_simple = old
    notes.append(f"Evaluation top-3 before {before['top3']:.1%}, after {after['top3']:.1%} "
                 f"(top-1 {before['top1']:.1%} to {after['top1']:.1%}).")
    if after["top3"] < before["top3"] - 1e-9:
        problems.append("Retrieval quality on the evaluation questions got worse.")
    return not problems, problems + notes


def read_proposal(path):
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    header, body, in_body = {}, [], False
    for line in lines:
        if not in_body and ":" in line and not line.strip() == "":
            k, v = line.split(":", 1)
            header[k.strip().lower()] = v.strip()
        elif not in_body and line.strip() == "":
            in_body = True
        else:
            body.append(line)
    return header, " ".join(l.strip() for l in body if l.strip())


def main(argv=None):
    ap = argparse.ArgumentParser(description="Privacy-preserving, human-approved improvement tools.")
    ap.add_argument("command", choices=["report", "propose", "check", "approve", "eval"])
    ap.add_argument("target", nargs="?")
    ap.add_argument("--min", type=int, default=5)
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args(argv)

    if args.command == "report":
        snap = Metrics().snapshot()
        print("Aggregate counters only (no chat text, no players, no roles, no timestamps).")
        print("Events:", snap.get("events", {}))
        rows = weak_sections(snap, args.min)
        if not rows:
            print(f"No section has {args.min}+ questions yet.")
        for r in rows:
            flag = "  <-- needs a clearer explanation" if r["needs_work"] else ""
            print(f"{r['id']:<62} asked={r['asked']:<4} unhelpful={r['unhelpful_rate']:.0%} confused={r['confusion_rate']:.0%}{flag}")
        return 0

    if args.command == "eval":
        res = run_eval(Engine(), verbose=True)
        print(f"{res['total']} questions: top-1 {res['top1']:.1%}, top-3 {res['top3']:.1%}")
        return 0

    engine = Engine()
    if args.command == "propose":
        chunk = engine.kb.get(args.target or "")
        if chunk is None:
            print("Unknown section id. Known ids:\n  " + "\n  ".join(c.id for c in engine.kb.chunks))
            return 2
        text, how = draft_simple_explanation(chunk, load_settings())
        PROPOSALS.mkdir(parents=True, exist_ok=True)
        path = PROPOSALS / f"{chunk.id}.md"
        path.write_text(f"chunk: {chunk.id}\ngenerated_by: {how}\nstatus: pending human review\n\n{text}\n", encoding="utf-8")
        print(f"Draft written to {path}\nEdit it if needed, then run:  python -m chatbot.improve check {path}")
        return 0

    header, text = read_proposal(args.target)
    chunk = engine.kb.get(header.get("chunk", ""))
    if chunk is None:
        print("The proposal does not name a valid 'chunk:' id.")
        return 2
    ok, messages = check_proposal(chunk, text, engine)
    for m in messages:
        print(("- " if not m.startswith("Evaluation") and not m.startswith("Many") else "  ") + m)
    print("CHECKS PASSED" if ok else "CHECKS FAILED")
    if args.command == "check":
        return 0 if ok else 1
    if not ok:
        return 1
    if not args.yes:
        print("Checks passed. A human must confirm: re-run with --yes to approve.")
        return 0
    APPROVED.mkdir(parents=True, exist_ok=True)
    (APPROVED / f"{chunk.id}.md").write_text(f"chunk: {chunk.id}\n{text}\n", encoding="utf-8")
    Path(args.target).unlink(missing_ok=True) if sys.version_info >= (3, 8) else None
    print(f"Approved: {APPROVED / (chunk.id + '.md')}  (applies to the simple explanation only)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
