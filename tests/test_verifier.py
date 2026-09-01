"""Golden-case tests for the deterministic verifier.

These cases encode real bugs we hit in production so a regression can never
silently re-introduce them:
  * Q9/Q10 old-edition article numbers that must count as correct (not hallucination)
  * Q5 cross-law equivalence (增值税暂行条例 ↔ 营改增实施办法)
  * temporal-trap: citing a repealed law (合同法) for a 民法典 question = ✗T
  * same cited provision as an equivalent (公司法43) must NOT be flagged ✗T
"""
from verifier import (
    Equivalence,
    HALLUCINATION_STATUSES,
    citation_key,
    extract_citations,
    parse_ref,
    verify,
)

from conftest import CONFIG


def load_eq():
    return Equivalence.load(CONFIG / "statute_equivalence.json")


def q(qid, citation):
    return {"qid": qid, "domain": "x", "prompt": "p",
            "expected_citation": citation, "verifiable": True}


def test_parse_ref_basic():
    assert parse_ref("《民法典》第584条") == ("民法典", 584)
    # clause (款) is ignored — article granularity only
    assert parse_ref("《中华人民共和国刑法》第20条第2款") == ("刑法", 20)
    assert parse_ref("《公司法》第一百七十七条") == ("公司法", 177)


def test_extract_citations_clause_and_multiple():
    cs = extract_citations("依据《民法典》第496条和《民法典》第584条，以及《刑法》第20条。")
    assert "《民法典》第496条" in cs
    assert "《民法典》第584条" in cs
    assert "《刑法》第20条" in cs


def test_citation_key_ignores_clause():
    assert citation_key("《民法典》第496条第2款") == citation_key("《民法典》第496条")


def test_equivalence_company_old_article():
    e = load_eq()
    # 2018 company law article -> 2023 canonical
    assert e.canonical("公司法", 43) == ("公司法", 66)
    assert e.canonical("公司法", 177) == ("公司法", 224)
    assert e.canonical("公司法", 33) == ("公司法", 57)
    assert e.canonical("公司法", 13) == ("公司法", 10)


def test_verify_old_article_is_correct():
    e = load_eq()
    r = verify(q(9, "《公司法》第66条"),
               "根据《公司法》第四十三条，须经三分之二以上表决权通过。", e)
    assert r["status"] == "✓"


def test_verify_vat_cross_law_equivalence():
    e = load_eq()
    # Q5 expected is now the current 增值税法 第22条. 营改增27条 is canonically
    # equivalent -> must still be accepted as correct.
    r = verify(q(5, "《增值税法》第22条"),
               "依据《营业税改征增值税试点实施办法》第二十七条，下列进项税额不得抵扣。", e)
    assert r["status"] == "✓"
    # 增值税暂行条例第10条 is also canonically equivalent (historical) -> correct.
    r = verify(q(5, "《增值税法》第22条"),
               "依据《增值税暂行条例》第10条，下列进项税额不得抵扣。", e)
    assert r["status"] == "✓"


def test_verify_wrong_article_is_hallucination():
    e = load_eq()
    r = verify(q(9, "《公司法》第66条"),
               "根据《公司法》第九十九条，由董事会决定。", e)
    assert r["status"] == "✗MA"


def _real_question(qid):
    """Load a question dict from the curated questions.json (carries also_correct)."""
    import json
    data = json.loads((CONFIG / "questions.json").read_text(encoding="utf-8"))
    return next(x for x in data["questions"] if x["qid"] == qid)


def test_verify_also_correct_distinct_but_valid():
    """A model citing a DIFFERENT but equally-correct article must NOT be
    falsely flagged ✗MA (accuracy safeguard against inflated HVI)."""
    e = load_eq()
    # Q1 expected 584; 577 (违约责任一般规定) is also correct — cite ONLY 577
    r = verify(_real_question(1),
               "买方违约，卖方可依《民法典》第577条请求损害赔偿，这是违约责任的一般规定。", e)
    assert r["status"] == "✓"
    assert "同样正确" in r["detail"]
    # Q14 expected 658; 663 (法定撤销) is also correct — cite ONLY 663
    r = verify(_real_question(14),
               "受赠人严重侵害赠与人权益的，赠与人可依《民法典》第663条撤销赠与。", e)
    assert r["status"] == "✓"


def test_verify_also_correct_does_not_mask_wrong_article():
    """also_correct must not let a genuinely wrong citation pass."""
    e = load_eq()
    r = verify(_real_question(1),
               "依据《刑法》第264条（盗窃罪），卖方应赔偿。", e)
    assert r["status"] == "✗MA"


def test_verify_nocite():
    e = load_eq()
    r = verify(q(1, "《民法典》第584条"), "这个需要结合具体情况判断。", e)
    assert r["status"] == "·"


def test_verify_temporal_trap_is_t():
    e = load_eq()
    # 民法典 question, model cites repealed 合同法 -> temporal hallucination
    r = verify(q(1, "《民法典》第584条"),
               "依据《合同法》第52条，该合同无效。", e)
    assert r["status"] == "✗T"


def test_verify_equivalent_old_article_is_not_temporal():
    e = load_eq()
    # 公司法43 is the OLD equivalent of 66 -> correct, NOT temporal
    r = verify(q(9, "《公司法》第66条"), "《公司法》第四十三条。", e)
    assert r["status"] == "✓"


def test_acceptable_citations_requires_actual_citation():
    """A wrong citation on a question that HAS acceptable_citations must NOT be
    auto-passed. Regression guard for the free-pass bug (the acceptable_citations
    branch must check the model's actual cited provision, not just that the
    acceptable article's canonical equals the expected)."""
    e = load_eq()
    # Q9 expected 66, acceptable 43. Citing a wrong article (99) -> ✗MA.
    r = verify(q(9, "《公司法》第66条"),
               "根据《公司法》第九十九条，由董事会决定。", e)
    assert r["status"] == "✗MA"
    # Citing the acceptable old article (43) -> ✓.
    r2 = verify(q(9, "《公司法》第66条"),
                "根据《公司法》第四十三条，须经三分之二以上表决权通过。", e)
    assert r2["status"] == "✓"


def test_q31_equity_transfer_scoring():
    """Q31 (newly added): current law 84 -> ✓; old-law acceptable 71 -> ✓;
    a wrong article -> ✗MA (not auto-passed via acceptable_citations)."""
    e = load_eq()
    q31 = _real_question(31)
    assert verify(q31, "根据《公司法》第84条，其他股东在同等条件下有优先购买权。", e)["status"] == "✓"
    assert verify(q31, "根据《公司法》第七十一条，经其他股东过半数同意方可转让。", e)["status"] == "✓"
    assert verify(q31, "根据《公司法》第20条，正当防卫。", e)["status"] == "✗MA"


def test_verify_english_citation():
    e = load_eq()
    r = verify(q(1, "《民法典》第584条"),
               "Under Article 584 of the Civil Code, lost profits are recoverable.", e)
    assert r["status"] == "✓"
    r2 = verify(q(9, "《公司法》第66条"),
                "Article 66 of the Company Law requires a two-thirds majority.", e)
    assert r2["status"] == "✓"


def test_hallucination_status_includes_temporal():
    assert "✗T" in HALLUCINATION_STATUSES
    assert "✗MA" in HALLUCINATION_STATUSES


def test_verify_repealed_vat_reg_on_non_vat_question_is_temporal():
    e = load_eq()
    # 增值税暂行条例 was repealed by 增值税法 (Art 38, eff 2026-01-01).
    # Cited on a 民法典 question (outside its equivalence group) -> temporal hallucination.
    r = verify(q(1, "《民法典》第584条"),
               "依据《增值税暂行条例》第10条，进项税额不得抵扣。", e)
    assert r["status"] == "✗T"


def test_repealed_predecessors_declared_in_repealed_laws():
    # Guard against drift: every law's repealed_predecessors must also appear
    # in the top-level repealed_laws list, or temporal-hallucination detection
    # silently misses a repealed law. (Caught 增值税暂行条例 missing on 2026-08-14.)
    e = load_eq()
    raw = e.raw
    missing = []
    for law, info in raw.get("laws", {}).items():
        for p in info.get("repealed_predecessors", []):
            if p not in raw.get("repealed_laws", []):
                missing.append((law, p))
    assert not missing, f"repealed_predecessors not declared in repealed_laws: {missing}"


def test_verify_nonexistent_article_is_not_found():
    """Q36 expected 公司法第162条. Citing a non-existent article number
    (公司法第999条, well beyond the 266-article cap) must be ✗NF (NOT_FOUND),
    NOT ✗MA — the provision does not exist, distinct from a wrong-but-real one."""
    e = load_eq()
    r = verify(q(36, "《公司法》第162条"),
               "依据《公司法》第999条，决议由董事会作出。", e)
    assert r["status"] == "✗NF"
    assert "不存在" in r["detail"]


def test_verify_wrong_but_existing_article_still_ma():
    """Regression: ✗NF must NOT over-fire on a real article that is merely
    wrong for the question. 公司法第57条 exists (within [1,266]) -> ✗MA."""
    e = load_eq()
    r = verify(q(36, "《公司法》第162条"),
               "依据《公司法》第57条，股东会有权修改章程。", e)
    assert r["status"] == "✗MA"


def test_verify_nf_only_for_known_law():
    """A law absent from article_ranges (e.g. 行政处罚法) citing a high number
    must fall back to ✗MA, never a false ✗NF (we lack a corpus to assert
    non-existence for that law)."""
    e = load_eq()
    r = verify(q(1, "《民法典》第584条"),
               "依据《行政处罚法》第999条，应予处罚。", e)
    assert r["status"] == "✗MA"


def test_verify_nf_does_not_override_temporal():
    """Precedence: a repealed-law citation with an out-of-range article
    (合同法第999条) is still ✗T (temporal), not ✗NF — temporal wins."""
    e = load_eq()
    r = verify(q(1, "《民法典》第584条"),
               "依据《合同法》第999条，该合同无效。", e)
    assert r["status"] == "✗T"


def test_verify_nf_across_laws():
    """A non-existent article in another law (刑法第999条, cap 452) -> ✗NF."""
    e = load_eq()
    r = verify(q(33, "《刑法》第20条"),
               "依据《刑法》第999条，正当防卫不负刑事责任。", e)
    assert r["status"] == "✗NF"


def test_hallucination_statuses_exactly_ma_t_and_nf():
    # Regression guard: the deterministic verifier emits ✗MA, ✗T and ✗NF as
    # hallucinations. ✗F (content-faithfulness / bare factual error) is still
    # NOT produced (would need an LLM judge, out of scope). This locks the
    # taxonomy so dead status labels cannot be re-introduced silently.
    assert HALLUCINATION_STATUSES == {"✗MA", "✗T", "✗NF"}
    assert "✗NF" in HALLUCINATION_STATUSES
    assert "✗F" not in HALLUCINATION_STATUSES
