"""Tests for sample aggregation and the leaderboard metric redesign.

Key guarantees:
  * HVI = wrong / (correct + wrong)              — pure citation hallucination rate
  * Coverage = (correct+wrong) / (correct+wrong+nocite) — evasion is visible, not exempt
  * Integrity = correct / (correct+wrong+nocite) — evasion penalized as not-correct
  * API failures (✗ERR) are excluded from the model-behavior denominators and
    reported separately as api_errors (never silently turned into nocite).
  * Temporal = temporal / (correct+wrong) — share of citations that are
    temporal/version hallucinations (✗T). ✗T is already inside total_cited,
    so the denominator must NOT add it again.
"""
from run_eval import aggregate_samples, build_leaderboard


def mk(status):
    return {"status": status, "detail": "d", "citations": []}


def _q(qid):
    return {"qid": qid, "domain": "x", "prompt": "p",
            "expected_citation": "《民法典》第584条", "verifiable": True}


def test_aggregate_majority():
    recs = [("a", mk("✓")), ("a", mk("✗MA")), ("a", mk("✓"))]
    agg = aggregate_samples("M", _q(1), recs, 3)
    assert agg["status"] == "✓"            # 2/3 majority
    assert agg["_correct"] == 2
    assert agg["_wrong"] == 1


def test_aggregate_tiebreak_prefers_hallucination():
    # 1 each of ✓ / ✗MA / · : tie broken toward ✗MA (conservative for a watch board)
    recs = [("a", mk("✓")), ("a", mk("✗MA")), ("a", mk("·"))]
    agg = aggregate_samples("M", _q(1), recs, 3)
    assert agg["status"] == "✗MA"


def test_aggregate_api_error_status():
    recs = [("", mk("✗ERR")), ("", mk("✗ERR")), ("a", mk("✓"))]
    agg = aggregate_samples("M", _q(1), recs, 3)
    assert agg["_api_err"] == 2
    assert agg["_correct"] == 1


def test_build_leaderboard_metrics():
    qs = [_q(i) for i in range(3)]
    recs = [
        aggregate_samples("M1", qs[0], [("a", mk("✓"))] * 3, 3),
        aggregate_samples("M1", qs[1], [("a", mk("✓")), ("a", mk("✓")), ("a", mk("·"))], 3),
        aggregate_samples("M1", qs[2], [("a", mk("✗MA")), ("a", mk("✓")), ("a", mk("✓"))], 3),
    ]
    lb = build_leaderboard({"M1": recs})
    r = lb[0]
    # correct=7, wrong=1 => total_cited=8 => hvi=1/8
    assert abs(r["hvi"] - 1 / 8) < 1e-9
    assert abs(r["crfi"] - 7 / 8) < 1e-9
    # nocite=1 => coverage = 8/9, integrity = 7/9 (rounded to 4 dp by build_leaderboard)
    assert abs(r["coverage"] - round(8 / 9, 4)) < 1e-9
    assert abs(r["integrity"] - round(7 / 9, 4)) < 1e-9
    assert r["citations"] == 3
    assert r["api_errors"] == 0


def test_build_leaderboard_api_error_separated():
    recs = [aggregate_samples("M2", _q(0), [("", mk("✗ERR"))] * 3, 3)]
    lb = build_leaderboard({"M2": recs})
    r = lb[0]
    assert r["hvi"] is None           # no citation-bearing samples
    assert r["coverage"] is None
    assert r["api_errors"] == 3       # but the failure is reported, not hidden


def test_build_leaderboard_temporal_metric():
    qs = [_q(i) for i in range(4)]
    recs = [
        aggregate_samples("M", qs[0], [("a", mk("✓"))] * 3, 3),            # correct
        aggregate_samples("M", qs[1], [("a", mk("✗T"))] * 3, 3),            # temporal
        aggregate_samples("M", qs[2], [("a", mk("✗MA"))] * 3, 3),          # other hallucination
        aggregate_samples("M", qs[3], [("a", mk("✗T")), ("a", mk("✓")), ("a", mk("✓"))], 3),
    ]
    lb = build_leaderboard({"M": recs})
    r = lb[0]
    # correct=5, wrong=7 => total_cited=12; temporal=4 (Q1×3 + Q3×1)
    assert abs(r["hvi"] - round(7 / 12, 4)) < 1e-9
    assert abs(r["temporal"] - round(4 / 12, 4)) < 1e-9     # NOT 4/16 (the double-count bug)
    assert r["temporal"] != round(4 / 16, 4)


def test_build_leaderboard_ranking_by_hvi():
    qs = [_q(i) for i in range(1)]
    good = aggregate_samples("Good", _q(0), [("a", mk("✓"))] * 3, 3)
    bad = aggregate_samples("Bad", _q(0), [("a", mk("✗MA"))] * 3, 3)
    lb = build_leaderboard({"Bad": [bad], "Good": [good]})
    assert lb[0]["model"] == "Good"
    assert lb[1]["model"] == "Bad"
    assert lb[0]["rank"] == 1
    assert lb[1]["rank"] == 2
