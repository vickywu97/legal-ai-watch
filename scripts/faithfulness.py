#!/usr/bin/env python3
"""
faithfulness.py — 内容忠实度初判 (✗F) · 纯标准库 · 确定性 · 可复现

这是 verifier 的**可选增强层**（默认关闭，见 verifier.verify() 的 faithfulness= 参数）。
它不改动确定性主基线（✓/✗MA/✗T/✗NF），只在之上叠加"引注条号对但内容不忠实"的判定。

方法（PoC，stdlib-only，无 embedding / 无 API）：
1. 取模型作答全文，与所引法条的**官方全文**做字符二元文法比较，指标为
   **containment = |A∩B| / |A|**（A=答案 bigram 集，B=官方正文 bigram 集），
   即"答案有多大比例的内容落在官方正文里"。
2. containment < 阈值（默认 0.45）→ 判 ✗F（内容表述不忠实）。

为什么不用 Jaccard（|A∩B|/|A∪B|）——改用 containment 的实测依据：
  Jaccard 的分母含并集，官方正文越长、并集越大、分数被系统性压低，导致
  **答对的简洁回答被误判**。以 8 组标注样本实测（tests/test_faithfulness.py
  的 TestCalibrationProbe，参考取官方全文）：
    公司法#162 的「答对」样本 Jaccard=0.093 → 误判 ✗F；
    且判别力崩塌——该「答对」样本(0.093) 竟低于「答错」样本(0.108)。
  containment 对参考长度不敏感：忠实样本 0.538–0.857，不忠实样本 0.129–0.387，
  中间留出干净空隙 (0.387, 0.538)；默认阈值 0.45 落在空隙内、偏不忠实侧以更好
  召回真实失真，同时距最低忠实样本仍有 0.088 余量（宁可漏报、不可误报）。
  语义上 containment 也更贴合"忠实"的定义：我们问的是"模型说的话有没有官方依据"，
  而不是"模型有没有把整条法复述一遍"。

3. 官方正文来源 config/article_texts.json，键为 "law#article"（canonical 形式，
   与 verifier.normalize_law_name 一致）。正文逐条摘自 legal-hallucination-bench
   的 knowledge_base/laws/statutes.jsonl（2327 条，verification_status 全 verified，
   源自全国人大/中国政府网官方文本），**不凭记忆撰写**；仍缺正文的法条登记在
   该文件的 _uncovered 字段，留待补充官方原文。
   某法条无正文时 is_faithful() 返回 None（跳过，不判 ✗F）——保证未覆盖法条绝不误报。

设计权衡：相比设计草案的方案 B（embedding 相似度），本 PoC 用字符二元文法 +
纯标准库实现，零依赖、零 API、完全可复现，契合项目"确定性、可审计"原则；代价是
语义粒度较粗，仅能捕获较极端的内容失真。0.30 系 7 样本探针的初始标定，仍须以
更大标注样本复核（见 docs/XF_CONTENT_FAITHFULNESS_DESIGN.md）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

# Punctuation / whitespace to strip before bigram extraction.
_PUNCT = set(" ，。、；：？！\"'（）()《》〈〉[]【】—…·\t\n\r 　\"'’")

_CN_RE = re.compile(r"[\u4e00-\u9fff]")  # CJK ideographs (unused placeholder for future)


def normalize_text(s: str) -> str:
    """Strip punctuation/whitespace; keep CJK + alphanumerics (lowercased)."""
    if not s:
        return ""
    out = []
    for ch in s:
        if ch in _PUNCT or ch.isspace():
            continue
        out.append(ch.lower())
    return "".join(out)


def char_bigrams(s: str) -> set:
    s = normalize_text(s)
    if len(s) < 2:
        return set(s)  # single char -> itself as a 1-gram fallback
    return {s[i:i + 2] for i in range(len(s) - 1)}


def jaccard(a: str, b: str) -> float:
    """Jaccard similarity of two strings' character-bigram sets, in [0, 1].

    Kept for comparison / ablation only — it is NOT the default metric because
    its denominator (the union) grows with the reference text, which
    systematically depresses scores for short answers measured against long
    official articles. See the module docstring.
    """
    A, B = char_bigrams(a), char_bigrams(b)
    if not A and not B:
        return 1.0
    if not A or not B:
        return 0.0
    inter = len(A & B)
    union = len(A | B)
    return inter / union if union else 0.0


def containment(answer: str, reference: str) -> float:
    """Fraction of `answer`'s bigrams that occur in `reference`, in [0, 1].

    |A∩B| / |A|  where A = answer bigrams, B = reference bigrams.

    Length-robust by construction: the denominator does NOT grow with the
    reference, so a correct but concise answer is not penalised for the official
    article being long. This is the metric "is what the model said grounded in
    the official text", which is what faithfulness actually asks — as opposed to
    "did the model reproduce the whole provision".
    """
    A, B = char_bigrams(answer), char_bigrams(reference)
    if not A:
        return 0.0
    return len(A & B) / len(A)


# Default metric + threshold. With the FULL official article text as reference
# and containment as the metric, the calibration probe
# (tests/test_faithfulness.py::TestCalibrationProbe) yields a clean gap:
#   unfaithful cluster  max = 0.387   (民法典#188 "二十年" error)
#   faithful cluster    min = 0.538   (公司法#162 short-but-correct summary)
# 0.45 sits inside that gap, placed toward the unfaithful side for better recall
# of real distortions while keeping an 0.088 margin below the lowest faithful
# sample (this layer must not false-flag correct answers).
DEFAULT_METRIC = "containment"
DEFAULT_THRESHOLD = 0.45

_METRICS = {"containment": containment, "jaccard": jaccard}


class FaithfulnessChecker:
    """Deterministic content-faithfulness checker (optional verifier layer)."""

    def __init__(self, article_texts: dict, threshold: float = DEFAULT_THRESHOLD,
                 min_len: int = 8, metric: str = DEFAULT_METRIC):
        # Normalize keys to "law#article" strings.
        self.texts = {str(k): str(v) for k, v in (article_texts or {}).items()}
        self.threshold = float(threshold)
        self.min_len = int(min_len)
        if metric not in _METRICS:
            raise ValueError(
                f"unknown metric {metric!r}; expected one of {sorted(_METRICS)}"
            )
        self.metric = metric
        self._sim = _METRICS[metric]

    @classmethod
    def load(cls, path: Path, threshold: float = DEFAULT_THRESHOLD,
             min_len: int = 8, metric: str = DEFAULT_METRIC):
        p = Path(path)
        if not p.exists():
            return cls({}, threshold=threshold, min_len=min_len, metric=metric)
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return cls({}, threshold=threshold, min_len=min_len, metric=metric)
        texts = data.get("article_texts", data) if isinstance(data, dict) else {}
        return cls(texts, threshold=threshold, min_len=min_len, metric=metric)

    def key(self, law: str, article: int) -> str:
        return f"{law}#{article}"

    def text_for(self, law: str, article: int) -> str | None:
        return self.texts.get(self.key(law, article))

    def score(self, answer: str, law: str, article: int) -> float | None:
        """Faithfulness score [0,1] of `answer` vs the official text, or None."""
        official = self.text_for(law, article)
        if not official:
            return None
        return self._sim(answer, official)

    def is_faithful(self, answer: str, law: str, article: int) -> bool | None:
        """True=faithful, False=unfaithful (✗F), None=skip (no official text / too short)."""
        official = self.text_for(law, article)
        if not official:
            return None
        if len(normalize_text(answer)) < self.min_len:
            return None
        return self._sim(answer, official) >= self.threshold
