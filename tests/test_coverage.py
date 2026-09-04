"""Regression guard for the benchmark coverage diagnostic + candidate draft.

These tests are offline and stdlib-only; they protect the "扩题" workflow:
- coverage_report.main() runs and reports on the current library;
- every candidate in questions_candidates.draft.json resolves to an existing
  verified article_texts entry (so merging it would not create a ✗F gap).
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def test_coverage_report_runs():
    from coverage_report import main
    import io
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        rc = main()
    finally:
        sys.stdout = old
    assert rc == 0
    out = buf.getvalue()
    assert "基准覆盖诊断" in out
    assert "参考库" in out


def test_candidate_draft_citations_all_covered():
    """Every candidate expected_citation must hit a verified article_texts key."""
    from verifier import parse_ref

    at = json.load(open(ROOT / "config" / "article_texts.json", encoding="utf-8"))[
        "article_texts"
    ]
    draft = json.load(
        open(ROOT / "config" / "questions_candidates.draft.json", encoding="utf-8")
    )
    assert draft.get("_STATUS") == "CANDIDATE_UNVERIFIED", "草稿不得被误当真值"
    cands = draft["candidates"]
    assert len(cands) >= 1
    seen = set()
    for c in cands:
        law, art = parse_ref(c["expected_citation"])
        key = f"{law}#{art}"
        assert key in at, f"Q{c['qid']} 引注 {c['expected_citation']} 无参考全文"
        assert c["qid"] not in seen, f"qid 重复: {c['qid']}"
        seen.add(c["qid"])
