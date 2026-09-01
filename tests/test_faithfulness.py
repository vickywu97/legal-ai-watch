#!/usr/bin/env python3
"""Tests for the optional ✗F content-faithfulness checker (stdlib-only PoC)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from faithfulness import (
    FaithfulnessChecker,
    char_bigrams,
    jaccard,
    normalize_text,
)


def test_normalize_strips_punct():
    assert normalize_text("《民法典》第577条：继续履行。") == "民法典第577条继续履行"


def test_jaccard_identical_is_one():
    assert jaccard("abcdef", "abcdef") == 1.0


def test_jaccard_disjoint_is_zero():
    assert jaccard("甲方", "乙方") == 0.0


def test_char_bigrams_len1_fallback():
    assert char_bigrams("甲") == {"甲"}


def test_is_faithful_true_when_overlap():
    texts = {"民法典#577": "当事人一方不履行合同义务或者履行合同义务不符合约定的，应当承担继续履行、采取补救措施或者赔偿损失等违约责任。"}
    chk = FaithfulnessChecker(texts, threshold=0.15)
    ans = "根据民法典第577条，如果对方不履行合同义务或者履行不符合约定，应承担继续履行、采取补救措施或赔偿损失等违约责任。"
    assert chk.is_faithful(ans, "民法典", 577) is True


def test_is_faithful_false_when_unrelated():
    texts = {"民法典#577": "当事人一方不履行合同义务或者履行合同义务不符合约定的，应当承担继续履行、采取补救措施或者赔偿损失等违约责任。"}
    chk = FaithfulnessChecker(texts, threshold=0.15)
    ans = "今天天气真好，我去公园散步，吃了冰淇淋，看完电影回家睡觉了。"
    assert chk.is_faithful(ans, "民法典", 577) is False


def test_is_faithful_none_when_no_text():
    chk = FaithfulnessChecker({}, threshold=0.15)
    assert chk.is_faithful("anything", "民法典", 577) is None


def test_is_faithful_none_when_too_short():
    texts = {"民法典#577": "当事人一方不履行合同义务或者履行合同义务不符合约定的，应当承担继续履行。"}
    chk = FaithfulnessChecker(texts, threshold=0.15)
    assert chk.is_faithful("好", "民法典", 577) is None


def test_score_none_when_missing():
    chk = FaithfulnessChecker({})
    assert chk.score("x", "民法典", 577) is None


def test_load_reads_article_texts_key():
    import json
    import tempfile
    import os
    data = {"article_texts": {"民法典#577": "x"}}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
        path = f.name
    try:
        chk = FaithfulnessChecker.load(Path(path))
        assert chk.text_for("民法典", 577) == "x"
    finally:
        os.unlink(path)
