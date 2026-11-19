"""Study demo of the four AI-subject topics kept in CAMORRA.

    python run_ai_lab.py                 run everything
    python run_ai_lab.py csp             Constraint Satisfaction (role assignment, day schedule)
    python run_ai_lab.py backtracking    Backtracking (8-Queens)
    python run_ai_lab.py hillclimb       Hill Climbing (table seating, maze)
    python run_ai_lab.py nlp "wat does the docter do at nigth?"     NLP pipeline used by the chatbot
"""
import random
import sys

from ai_lab import backtracking, csp, hillclimb, nlp

NAMES = ["Ali", "Sara", "Omar", "Hina", "Zain", "Maya", "Bilal", "Noor"]


def show(title):
    print("\n" + "=" * 70 + f"\n{title}\n" + "=" * 70)


def demo_backtracking():
    show("BACKTRACKING: 8-Queens (ai_lab/backtracking.py)")
    (first,), stats = backtracking.n_queens(8)
    print("First solution (column -> row):", first, "| work:", stats)
    sols, stats = backtracking.n_queens(8, find_all=True)
    print(f"All solutions: {len(sols)} (the known answer is 92) | work: {stats}")
    for r in range(8):
        print(" ".join("Q" if first[c] == r else "." for c in range(8)))


def demo_csp():
    show("CSP: role assignment and day schedule (ai_lab/csp.py)")
    sol, stats, need = csp.role_assignment(NAMES, 2, forbidden_mafia=["Ali"])
    print("Required counts:", need)
    print("Solution:", sol)
    print("Solver work:", stats, "(it backtracks whenever a rule is broken)")
    ok, _, _ = csp.verify_role_assignment(sol)
    print("Verified against the game's role-count rules:", ok)
    slots, stats, before = csp.day_schedule()
    print("Day schedule (phase -> slot):", slots)


def demo_hillclimb():
    show("HILL CLIMBING: seating and maze (ai_lab/hillclimb.py)")
    roster = {n: r for n, r in zip(NAMES, ["Mafia", "Mafia", "Detective", "Doctor", "Villager", "Villager", "Villager", "Villager"])}
    for run in hillclimb.seating_demo(roster, seed=3):
        print(f"{run['variant']:<10} score {run['start_score']} -> {run['final_score']} in {run['steps']} steps  history={run['score_history']}")
    m = hillclimb.maze_demo()
    print("\n".join(m["maze"]))
    for run in m["runs"]:
        print(f"{run['variant']:<10} reached goal: {run['reached_goal']}, stopped at {run['stopped_at']} (local maximum if not the goal)")


def demo_nlp(text):
    show("NLP: the chatbot's explicit pipeline (ai_lab/nlp.py + chatbot/)")
    from chatbot.engine import Engine
    E = Engine()
    u = E.understanding
    tokens = nlp.tokenize(text)
    print("Message               :", text)
    print("1. Tokenization       :", tokens)
    fixed = [nlp.correct_spelling(t, u.vocab, u.protected) for t in tokens]
    print("2. Spelling correction:", fixed, "  (edit distance, only for words the game knows)")
    lemmas = nlp.normalize(fixed, u.vocab)
    print("3. Lemmatization      :", lemmas)
    print("   (stemming, for comparison):", [nlp.stem(t) for t in fixed])
    a = u.analyse(text)
    print("4. Entities (NER)     :", [(e.type, e.name) for e in a.entities])
    print("5. Intent scores      :", {k: round(v, 1) for k, v in sorted(a.intent_scores.items(), key=lambda kv: -kv[1])[:4]})
    print("   Chosen intent      :", a.intent)
    print("6. Bag of words       :", dict(nlp.bag_of_words(a.content)))
    _, ents, hits, _ = E.interpret(text, None, None, "NIGHT")
    print("7. TF-IDF retrieval   :")
    for h in hits[:3]:
        print(f"     {h.score:.2f}  {h.chunk.label}")


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else "all"
    if arg in ("all", "backtracking"):
        demo_backtracking()
    if arg in ("all", "csp"):
        demo_csp()
    if arg in ("all", "hillclimb"):
        demo_hillclimb()
    if arg in ("all", "nlp"):
        demo_nlp(" ".join(sys.argv[2:]) or "wat does the docter do at nigth?")


if __name__ == "__main__":
    main()
