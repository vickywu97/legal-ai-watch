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
    r = verify(q(5, "《增值税暂行条例》第10条"),
               "依据《营业税改征增值税试点实施办法》第二十七条，下列进项税额不得抵扣。", e)
    assert r["status"] == "✓"


def test_verify_wrong_article_is_hallucination():
    e = load_eq()
    r = verify(q(9, "《公司法》第66条"),
               "根据《公司法》第九十九条，由董事会决定。", e)
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
