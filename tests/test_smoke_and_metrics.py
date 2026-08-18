"""Tests for the metrics math, the smoke (--limit) mode, and the answers.jsonl
error-field plumbing.

These run with a mocked model API (no paid calls) so the scoring logic and the
smoke-mode filesystem contract are provably correct offline. The only thing a
real run must verify is the live provider behavior — which is the product, not a bug.
"""
import json
from pathlib import Path

import pytest

from run_eval import (
    ModelCallError,
    aggregate_samples,
    build_domain_hvi,
    build_leaderboard,
    run_evaluation,
)
from verifier import verify, Equivalence, extract_citations, parse_ref

KEY_ENVS = ["DEEPSEEK_API_KEY", "ZHIPU_API_KEY", "DASHSCOPE_API_KEY", "MOONSHOT_API_KEY"]
CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
N_MODELS = sum(1 for m in json.loads((CONFIG_DIR / "models.json").read_text(encoding="utf-8"))["models"]
               if m.get("enabled", True))
N_QUESTIONS = len(json.loads((CONFIG_DIR / "questions.json").read_text(encoding="utf-8"))["questions"])
EQ = Equivalence.load(CONFIG_DIR / "statute_equivalence.json")


# ---------------------------------------------------------------------------
# Pure scoring math — no API, no config questions needed
# ---------------------------------------------------------------------------
def _verif(status, domain="税", correct=0, wrong=0, nocite=0, temporal=0, api_err=0):
    return {"domain": domain, "status": status, "_correct": correct, "_wrong": wrong,
            "_nocite": nocite, "_temporal": temporal, "_api_err": api_err}


def test_build_leaderboard_metrics():
    """HVI = wrong/(correct+wrong); CRFI = correct/(correct+wrong);
    coverage = cited/engaged; integrity = correct/engaged; un-cited drags both."""
    model_results = {
        "M-A": [
            _verif("✓", correct=1),
            _verif("✓", correct=1),
            _verif("✗MA", wrong=1),
            _verif("·", nocite=1),
        ]
    }
    rows = build_leaderboard(model_results)
    assert len(rows) == 1
    r = rows[0]
    assert r["hvi"] == round(1 / 3, 4)
    assert r["crfi"] == round(2 / 3, 4)
    assert r["coverage"] == round(3 / 4, 4)
    assert r["integrity"] == round(2 / 4, 4)
    assert r["citations"] == 3
    assert r["api_errors"] == 0
    assert r["rank"] == 1


def test_build_leaderboard_no_cite_model():
    """A model that cites nothing verifiable gets HVI=None and is unranked."""
    model_results = {"M-Ghost": [_verif("·", nocite=1), _verif("·", nocite=1)]}
    rows = build_leaderboard(model_results)
    r = rows[0]
    assert r["hvi"] is None
    assert r["crfi"] is None
    assert r["rank"] is None
    assert r["answered"] == 2


def test_build_domain_hvi_ignores_unverifiable():
    model_results = {"M-A": [_verif("✓", domain="税", correct=1),
                              _verif("✗MA", domain="税", wrong=1),
                              _verif("·", domain="刑", nocite=1)]}
    dom = build_domain_hvi(model_results)["M-A"]
    assert dom["税"] == round(1 / 2, 4)
    assert dom["刑"] is None  # no citable sample in this domain


def test_aggregate_samples_hallucination_outranks_correct():
    """Tie (1✓ / 1✗MA) must resolve to the hallucination verdict (conservative)."""
    q = {"qid": "Q1", "domain": "税", "prompt": "p"}
    samples = [
        ("ans-correct", {"status": "✓", "detail": "对", "citations": []}),
        ("ans-wrong", {"status": "✗MA", "detail": "错引", "citations": []}),
    ]
    agg = aggregate_samples("M", q, samples, n_samples=2)
    assert agg["status"] == "✗MA"
    assert agg["_correct"] == 1 and agg["_wrong"] == 1


# ---------------------------------------------------------------------------
# Smoke (--limit) mode — filesystem contract, no history pollution
# ---------------------------------------------------------------------------
def _set_keys(monkeypatch, values):
    for env in KEY_ENVS:
        monkeypatch.setenv(env, values.get(env, ""))


def test_smoke_writes_to_smoke_dir_and_skips_history(tmp_path, monkeypatch):
    """--limit N must write under data/smoke/<date> and NOT create
    leaderboard_history.json (so the public board is untouched)."""
    def fake_call(model_cfg, prompt, api_key, system_prompt, **kw):
        return "未引用任何法条的回答。"   # -> verifier marks as 未引注 (·)

    monkeypatch.setattr("run_eval.call_model", fake_call)
    _set_keys(monkeypatch, {e: "dummy" for e in KEY_ENVS})

    run_evaluation("2026-08-17", tmp_path, samples=1, limit=2)

    smoke_dir = tmp_path / "smoke" / "2026-08-17"
    assert (smoke_dir / "verifications.jsonl").exists()
    assert (smoke_dir / "leaderboard.json").exists()
    assert (smoke_dir / "answers.jsonl").exists()
    # public board must remain untouched
    assert not (tmp_path / "leaderboard_history.json").exists()
    assert not (tmp_path / "answers").exists()
    # exactly limit * N_MODELS verification rows
    n_verifs = sum(1 for _ in (smoke_dir / "verifications.jsonl").read_text(encoding="utf-8").splitlines() if _.strip())
    assert n_verifs == N_MODELS * 2


def test_smoke_error_field_in_answers(tmp_path, monkeypatch):
    """When a model call fails, the error text must land in answers.jsonl `error`
    (so the public audit can show *why*, not just a bare ✗ERR)."""
    def fake_call(model_cfg, prompt, api_key, system_prompt, **kw):
        raise ModelCallError(f"{model_cfg['id']} HTTP 401 (auth/config error, not retried)")

    monkeypatch.setattr("run_eval.call_model", fake_call)
    _set_keys(monkeypatch, {e: "dummy" for e in KEY_ENVS})

    run_evaluation("2026-08-17", tmp_path, samples=1, limit=1)

    smoke_dir = tmp_path / "smoke" / "2026-08-17"
    lines = [json.loads(l) for l in (smoke_dir / "answers.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == N_MODELS
    for rec in lines:
        assert rec["error"] is not None
        assert "401" in rec["error"]
        assert rec["counts"] == {"✗ERR": 1}


def test_full_mode_default_keeps_history(tmp_path, monkeypatch):
    """Sanity: without --limit, history IS written (default full behavior)."""
    def fake_call(model_cfg, prompt, api_key, system_prompt, **kw):
        return "未引用任何法条的回答。"

    monkeypatch.setattr("run_eval.call_model", fake_call)
    _set_keys(monkeypatch, {e: "dummy" for e in KEY_ENVS})

    run_evaluation("2026-08-17", tmp_path, samples=1)  # limit=0 -> full

    assert (tmp_path / "answers" / "2026-08-17" / "verifications.jsonl").exists()
    assert (tmp_path / "leaderboard_history.json").exists()


# ---------------------------------------------------------------------------
# Government-document citations (国发〔2022〕8号 etc.) — article-less parsing
# ---------------------------------------------------------------------------
def test_gov_doc_parsing():
    """A 国务院文件 citation has no article; it must parse to (doc_id, None)
    and be extracted verbatim, with both fullwidth and halfwidth brackets."""
    assert parse_ref("国发〔2022〕8号") == ("国发〔2022〕8号", None)
    assert parse_ref("财税〔2016〕36号") == ("财税〔2016〕36号", None)
    # optional 第 before serial must normalize to the same doc_id
    assert parse_ref("国发〔2022〕第8号") == ("国发〔2022〕8号", None)
    # halfwidth brackets must normalize to the same doc_id
    assert parse_ref("国发[2022]8号") == ("国发〔2022〕8号", None)
    assert extract_citations("依据国发〔2022〕8号及个税法第六条。") == ["国发〔2022〕8号"]
    # law citations must NOT be mis-captured as gov docs
    assert parse_ref("《个人所得税法》第6条") == ("个人所得税法", 6)


def test_q6_gov_doc_accepted_as_also_correct():
    """Q6: a model that lists the 7th item and cites ONLY 国发〔2022〕8号 must
    pass (✓) via also_correct — not be silently dropped (·) or falsely ✗MA."""
    q6 = {
        "qid": 6,
        "expected_citation": "《个人所得税法》第6条",
        "also_correct": [
            {"citation": "《个人所得税专项附加扣除暂行办法》第5条"},
            {"citation": "国发〔2022〕8号"},
        ],
        "verifiable": True,
    }
    ans = "专项附加扣除共7项，含3岁以下婴幼儿照护，依据国发〔2022〕8号设立。"
    res = verify(q6, ans, EQ)
    assert res["status"] == "✓", res
    # the 第-serial variant must also match Q6's also_correct
    res_d = verify(q6, "第7项依据国发〔2022〕第8号设立。", EQ)
    assert res_d["status"] == "✓", res_d
    # regression: a wrong citation still fails
    wrong = verify(q6, "共6项，依据《刑法》第264条。", EQ)
    assert wrong["status"] == "✗MA", wrong
    # the canonical 个税法第6条 answer still passes
    ok = verify(q6, "依据《个人所得税法》第6条。", EQ)
    assert ok["status"] == "✓", ok
