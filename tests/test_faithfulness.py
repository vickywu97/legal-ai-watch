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


# ---------------------------------------------------------------------------
# Calibration probe — locks the empirical separation property of the default
# metric (containment) + threshold (0.45) against the REAL full-text reference
# set (config/article_texts.json). Faithful answers must score above the
# threshold; unfaithful ones below it; and there must be a clean gap between the
# two clusters. If this regresses, the metric/threshold choice is broken.
# ---------------------------------------------------------------------------
CALIBRATION_CASES = [
    ("民法典", 188, True,
     "《民法典》第188条规定，向人民法院请求保护民事权利的诉讼时效期间为三年，法律另有规定的依照其规定。"),
    ("公司法", 162, True,
     "根据《公司法》第162条，公司不得收购本公司股份，但减少注册资本、与其他持股公司合并、员工持股计划或股权激励等六种法定情形除外。"),
    ("公司法", 57, True,
     "《公司法》第57条规定，股东有权查阅、复制公司章程、股东名册、股东会会议记录、董事会决议、监事会决议和财务会计报告，并可查阅会计账簿、会计凭证。"),
    ("公司法", 23, True,
     "《公司法》第23条规定，公司股东滥用公司法人独立地位和股东有限责任逃避债务，严重损害债权人利益的，应当对公司债务承担连带责任。"),
    ("民法典", 577, True,
     "《民法典》第577条规定，当事人一方不履行合同义务或者履行合同义务不符合约定的，应当承担继续履行、采取补救措施或者赔偿损失等违约责任。"),
    ("公司法", 162, False,
     "根据《公司法》第162条，股东有权随时要求公司分红，公司必须按月向股东支付股息。"),
    ("民法典", 188, False,
     "《民法典》第188条规定，合同纠纷的诉讼时效为二十年，自合同签订之日起计算。"),
    ("民法典", 23, False,
     "《民法典》第23条规定，无民事行为能力人订立的合同一律无效，相对人不得主张任何权利。"),
]


class TestCalibrationProbe:
    @classmethod
    def setup_class(cls):
        cls.chk = FaithfulnessChecker.load(
            Path(__file__).resolve().parent.parent / "config" / "article_texts.json"
        )
        assert cls.chk.metric == "containment"
        # Probe must run against the production default threshold.
        assert cls.chk.threshold == 0.45

    def test_separation_property(self):
        faithful, unfaithful = [], []
        for law, art, truth, ans in CALIBRATION_CASES:
            flag = self.chk.is_faithful(ans, law, art)
            assert flag is not None, f"{law}#{art} has no reference text"
            assert flag == truth, (
                f"{law}#{art}: expected faithful={truth}, got {flag}"
            )
            s = self.chk.score(ans, law, art)
            (faithful if truth else unfaithful).append(s)
        # Clean gap: lowest faithful strictly above highest unfaithful.
        assert min(faithful) > max(unfaithful), (
            f"no separation gap: faithful_min={min(faithful):.3f} "
            f"<= unfaithful_max={max(unfaithful):.3f}"
        )
