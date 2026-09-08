"""Tests for the v1.3 answer-level hallucination dimensions (watch verifier).

These run entirely offline (no API, no LLM). They mirror the semantics of
bench/answer_checks.py but exercise watch's self-contained verifier.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import verifier as V  # noqa: E402


class TestGuidingCases(unittest.TestCase):
    def setUp(self):
        V._GUIDING_CASES = None  # reset memoization

    def test_registry_loaded(self):
        reg = V.load_guiding_cases()
        self.assertEqual(reg, {1, 15, 24, 67})

    def test_fabricated_case_detected(self):
        is_fab, fab_list, cited = V.detect_fabricated_case(
            "根据《民法典》第584条……另可参见指导案例第999号佐证。")
        self.assertTrue(is_fab)
        self.assertEqual(fab_list, [999])
        self.assertTrue(cited)

    def test_real_guiding_case_ok(self):
        is_fab, fab_list, cited = V.detect_fabricated_case(
            "见指导案例第24号。")
        self.assertFalse(is_fab)
        self.assertEqual(cited, [24])

    def test_no_guiding_case(self):
        is_fab, fab_list, cited = V.detect_fabricated_case("仅引用《民法典》第584条。")
        self.assertFalse(is_fab)
        self.assertEqual(cited, [])


class TestCircularCitation(unittest.TestCase):
    def test_cycle_detected(self):
        text = ("依据《公司法》第15条，而第15条又引第16条，"
                "第16条复引第15条，形成闭环。")
        is_circ, nums = V.detect_circular_citation(text)
        self.assertTrue(is_circ)

    def test_explicit_phrase(self):
        self.assertTrue(V.detect_circular_citation("两条规定互为援引。")[0])

    def test_no_cycle(self):
        text = "《民法典》第584条规定损害赔偿。第585条规范违约金。"
        is_circ, _ = V.detect_circular_citation(text)
        self.assertFalse(is_circ)


class TestSelfContradiction(unittest.TestCase):
    def test_contradiction_detected(self):
        text = ("买方应当先支付价款。但买方无需先支付价款即可请求交货。"
                "合同自成立时生效。")
        self.assertTrue(V.detect_self_contradiction(text))

    def test_no_contradiction(self):
        text = "买方应当支付价款。卖方应当交付标的物。合同自成立时生效。"
        self.assertFalse(V.detect_self_contradiction(text))


class TestAnswerLevelFlags(unittest.TestCase):
    def test_flags_integrate(self):
        ans = ("根据《民法典》第584条。买方应当先付款。"
               "但买方无需先付款。另参见指导案例第999号。")
        flags = V.answer_level_flags(ans)
        self.assertTrue(flags["fabricated_case"])
        self.assertIn(999, flags["fabricated_cases"])
        self.assertTrue(flags["cited_guiding_case"])
        self.assertTrue(flags["self_contradiction"])


class TestVerifyAttachesFlags(unittest.TestCase):
    """run_eval.verify_answer must attach answer_flags without touching status."""

    def test_verify_answer_merges_flags(self):
        sys.path.insert(0, SCRIPTS)
        import run_eval  # noqa: F401  (ensures importability; lazy requests)
        # Build a minimal question + use verifier.verify directly to confirm the
        # flag helper is wired through run_eval.verify_answer.
        q = {"qid": "Q1", "domain": "民法", "prompt": "x",
             "verifiable": True, "expected_citation": "《民法典》第584条"}
        eq = V.Equivalence.load(
            os.path.join(SCRIPTS, "..", "config", "statute_equivalence.json"))
        # answer with a fabricated guiding case
        ans = "根据《民法典》第584条。另见指导案例第999号。"
        v = run_eval.verify_answer(q, ans, eq)
        self.assertIn("answer_flags", v)
        self.assertTrue(v["answer_flags"]["fabricated_case"])
        # status untouched (citation-level HVI source of truth)
        self.assertIn(v["status"], {"✓", "✗MA", "✗NF", "✗T", "✗F", "·", "?"})


if __name__ == "__main__":
    unittest.main()


class TestLeaderboardAnswerMetrics(unittest.TestCase):
    """Guard the hr_case / rate_circular / flag_self_contradiction aggregation
    math in run_eval.build_leaderboard (never affects HVI)."""

    def test_hr_case_fraction(self):
        import run_eval
        verifs = [
            {"status": "✓", "_fabricated_case": 0, "_cited_guiding_case": 1,
             "_circular": 0, "_self_contradiction": 0,
             "_correct": 1, "_wrong": 0, "_nocite": 0, "_temporal": 0,
             "_api_err": 0, "_unverif": 0},
            {"status": "✗MA", "_fabricated_case": 1, "_cited_guiding_case": 1,
             "_circular": 0, "_self_contradiction": 0,
             "_correct": 0, "_wrong": 1, "_nocite": 0, "_temporal": 0,
             "_api_err": 0, "_unverif": 0},
        ]
        rows = run_eval.build_leaderboard({"M": verifs})
        r = rows[0]
        self.assertIsNotNone(r["hr_case"])
        self.assertAlmostEqual(r["hr_case"], 0.5)  # 1 fabricated / 2 cited
        self.assertAlmostEqual(r["rate_circular"], 0.0)
        self.assertAlmostEqual(r["flag_self_contradiction"], 0.0)

    def test_hr_case_none_when_no_guiding_case(self):
        import run_eval
        verifs = [{"status": "✓", "_fabricated_case": 0, "_cited_guiding_case": 0,
                   "_circular": 0, "_self_contradiction": 0,
                   "_correct": 1, "_wrong": 0, "_nocite": 0, "_temporal": 0,
                   "_api_err": 0, "_unverif": 0}]
        rows = run_eval.build_leaderboard({"M": verifs})
        self.assertIsNone(rows[0]["hr_case"])

