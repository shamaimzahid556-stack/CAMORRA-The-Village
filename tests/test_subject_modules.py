"""The AI-subject modules that were kept: CSP, backtracking, hill climbing and NLP."""
import random
import unittest

import tests.helpers  # noqa: F401  (sets sys.path)
from ai_lab import backtracking, csp, hillclimb, nlp


class Backtracking(unittest.TestCase):
    def test_eight_queens_has_92_solutions(self):
        sols, stats = backtracking.n_queens(8, find_all=True)
        self.assertEqual(len(sols), 92)
        self.assertGreater(stats["backtracks"], 0)

    def test_first_solution_is_valid(self):
        (sol,), _ = backtracking.n_queens(8)
        rows = [sol[c] for c in range(8)]
        self.assertEqual(len(set(rows)), 8)
        self.assertTrue(all(abs(rows[i] - rows[j]) != j - i for i in range(8) for j in range(i + 1, 8)))

    def test_generic_solver_and_mrv_does_less_work(self):
        v = list("abcdef"); d = {x: [1, 2, 3, 4, 5, 6] for x in v}
        alldiff = lambda a: len(set(a.values())) == len(a)
        _, s1 = backtracking.backtrack(v, d, [alldiff], mrv=False)
        _, s2 = backtracking.backtrack(v, d, [alldiff], mrv=True)
        self.assertTrue(s1["assignments_tried"] >= 1 and s2["assignments_tried"] >= 1)

    def test_unsatisfiable_returns_no_solution(self):
        sols, _ = backtracking.backtrack(["a", "b"], {"a": [1], "b": [1]}, [lambda a: len(set(a.values())) == len(a)])
        self.assertEqual(sols, [])


class CSP(unittest.TestCase):
    NAMES = ["Ali", "Sara", "Omar", "Hina", "Zain", "Maya", "Bilal", "Noor"]

    def test_role_assignment_obeys_counts_and_constraints(self):
        sol, stats, need = csp.role_assignment(self.NAMES, 2, forbidden_mafia=["Ali"])
        self.assertEqual({r: list(sol.values()).count(r) for r in need}, need)
        self.assertNotEqual(sol["Ali"], "Mafia")
        idx = {n: i for i, n in enumerate(self.NAMES)}
        mafia = [n for n, r in sol.items() if r == "Mafia"]
        self.assertFalse(any(abs(idx[a] - idx[b]) in (1, len(self.NAMES) - 1) for a in mafia for b in mafia if a < b))

    def test_verify_role_assignment(self):
        good = dict(zip("abcdef", ["Mafia", "Detective", "Doctor", "Villager", "Villager", "Villager"]))
        ok, _, _ = csp.verify_role_assignment(good)
        self.assertTrue(ok)
        bad = dict(zip("abcdef", ["Mafia", "Detective", "Detective", "Villager", "Villager", "Villager"]))
        self.assertFalse(csp.verify_role_assignment(bad)[0])

    def test_day_schedule_respects_order(self):
        slots, _, before = csp.day_schedule()
        self.assertTrue(all(slots[a] < slots[b] for a, b in before))
        self.assertEqual(len(set(slots.values())), 5)

    def test_works_for_every_legal_game_size(self):
        for n in range(6, 16):
            names = [f"P{i}" for i in range(n)]
            for m in range(1, 4):
                sol, _, need = csp.role_assignment(names, m)
                self.assertIsNotNone(sol, (n, m))


class HillClimbing(unittest.TestCase):
    ROSTER = {"A": "Mafia", "B": "Mafia", "C": "Detective", "D": "Doctor", "E": "Villager", "F": "Villager", "G": "Villager"}

    def test_all_three_variants_never_get_worse(self):
        start = list(self.ROSTER)
        for kind in ("simple", "steepest", "stochastic"):
            r = hillclimb.climb(kind, start, self.ROSTER, random.Random(1))
            self.assertGreaterEqual(r["final_score"], r["start_score"])
            self.assertEqual(sorted(r["final_order"]), sorted(start))
            self.assertTrue(all(b > a for a, b in zip(r["score_history"], r["score_history"][1:])))

    def test_seating_demo_improves_a_random_seating(self):
        runs = hillclimb.seating_demo(self.ROSTER, seed=3)
        self.assertEqual(len(runs), 3)

    def test_maze_shows_local_maximum(self):
        runs = hillclimb.maze_demo()["runs"]
        self.assertTrue(all("reached_goal" in r for r in runs))
        self.assertFalse(all(r["reached_goal"] for r in runs))          # stuck in a dead end


class NLP(unittest.TestCase):
    def test_tokenization_and_contractions(self):
        self.assertEqual(nlp.tokenize("I can't vote!"), ["i", "can", "not", "vote"])
        self.assertEqual(nlp.tokenize("What's the Doctor's job?"), ["what", "is", "the", "doctor", "job"])

    def test_lemmatization_vs_stemming(self):
        self.assertEqual(nlp.lemmatize("voted"), "vote")
        self.assertEqual(nlp.lemmatize("was"), "be")
        self.assertEqual(nlp.lemmatize("investigating"), "investigate")
        self.assertEqual(nlp.stem("voted"), "vot")                      # a stem need not be a word

    def test_spelling_correction_is_conservative(self):
        vocab = {"detective", "doctor", "mafia", "vote", "note"}
        self.assertEqual(nlp.correct_spelling("detecive", vocab), "detective")
        self.assertEqual(nlp.correct_spelling("docter", vocab), "doctor")
        self.assertEqual(nlp.correct_spelling("note", vocab), "note")   # real word left alone
        self.assertEqual(nlp.correct_spelling("tell", vocab), "tell")   # short words never changed
        self.assertEqual(nlp.edit_distance("ab", "ba"), 1)

    def test_gazetteer_longest_match_first(self):
        g = nlp.Gazetteer({"BUTTON": {"BEGIN NEXT NIGHT": ["begin next night"]}, "PHASE": {"night": ["night"]}})
        lem = nlp.normalize(nlp.tokenize("press begin next night"))
        self.assertEqual([(t, n) for t, n, *_ in g.find(lem)], [("BUTTON", "BEGIN NEXT NIGHT")])

    def test_tfidf_ranks_the_relevant_document_first(self):
        idx = nlp.TfidfIndex([["detective", "investigate", "night"], ["vote", "eliminate"], ["doctor", "protect"]])
        sims = idx.similarities(["investigate", "detective"])
        self.assertEqual(sims.index(max(sims)), 0)
        chars = nlp.TfidfIndex([["detective"], ["voting"]], use_chars=True)
        self.assertGreater(chars.similarities(["detecive"])[0], chars.similarities(["detecive"])[1])


class CleanupWasSafe(unittest.TestCase):
    def test_removed_modules_are_gone_and_nothing_imports_them(self):
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        gone = ["adversarial", "analysis", "labs", "ml", "recorder", "search", "town"]
        for m in gone:
            self.assertFalse((root / "ai_lab" / f"{m}.py").exists(), m)
        self.assertFalse((root / "ai_lab" / "api.py").exists())
        self.assertFalse((root / "ai_lab" / "ui.html").exists())
        for py in list(root.rglob("*.py")):
            if "tests" in py.parts:
                continue
            src = py.read_text(encoding="utf-8")
            for m in gone:
                self.assertNotIn(f"ai_lab.{m}", src, f"{py} still references ai_lab.{m}")
                self.assertNotIn(f"from ai_lab import {m}", src, py)
        for kept in ("csp", "backtracking", "hillclimb", "nlp"):
            self.assertTrue((root / "ai_lab" / f"{kept}.py").exists())


if __name__ == "__main__":
    unittest.main()
