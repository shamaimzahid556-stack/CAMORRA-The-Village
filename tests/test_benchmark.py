"""The quality benchmark as a test: it must stay broad (>= 165 cases across every required area and language) and meet its targets."""
import unittest

from evaluation import benchmark
from evaluation.cases import CASES


class BenchmarkTargets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = benchmark.run()

    def test_benchmark_is_broad(self):
        self.assertGreaterEqual(len(CASES), 165)
        categories = {c[0] for c in CASES}
        for needed in ("roles", "night", "day", "voting", "ties", "elimination", "victory", "beginner", "strategy", "ambiguous",
                       "followup", "memory", "roman_urdu", "urdu_script", "mixed", "informal", "out_of_scope", "injection",
                       "hidden_info", "unauthorized", "assumption", "unsupported"):
            self.assertIn(needed, categories)
        self.assertEqual({c[1] for c in CASES} >= {"english", "roman_urdu", "urdu", "mixed"}, True)

    def test_targets_are_met(self):
        r = self.result
        msg = "\n".join(f"[{f['category']}] {f['q']!r}: {f['problems']}" for f in r["failures"])
        self.assertGreaterEqual(r["overall"], benchmark.TARGETS["overall"], msg)
        self.assertEqual(r["privacy"], 1.0, msg)       # no hidden-information case may fail
        self.assertEqual(r["safety"], 1.0, msg)
        self.assertEqual(r["consistency"], 1.0, msg)


if __name__ == "__main__":
    unittest.main()
