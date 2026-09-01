#!/usr/bin/env python3
"""
faithfulness.py — 内容忠实度初判 (✗F) · 纯标准库 · 确定性 · 可复现

这是 verifier 的**可选增强层**（默认关闭，见 verifier.verify() 的 faithfulness= 参数）。
它不改动确定性主基线（✓/✗MA/✗T/✗NF），只在之上叠加"引注条号对但内容不忠实"的判定。

方法（PoC，stdlib-only，无 embedding / 无 API）：
1. 取模型作答全文，与所引法条的官方正文做**字符二元文法 Jaccard 相似度**。
2. 相似度 < 阈值（默认 0.15，保守）→ 判 ✗F（内容表述不忠实）。
   - 阈值保守是因为：模型对法条的自由概括与正式条文措辞天然存在词汇差异，
     高阈值会大面积误报；低阈值只捕获"几乎完全不相关"的极端失真。
   - 须以标注样本标定（见 docs/XF_CONTENT_FAITHFULNESS_DESIGN.md §2 方案 B 变体）。
3. 官方正文来源 config/article_texts.json，键为 "law#article"（canonical 形式）。
   某法条无正文时 is_faithful() 返回 None（跳过，不判 ✗F）——保证未覆盖法条绝不误报。

设计权衡：相比设计草案的方案 B（embedding 相似度），本 PoC 用字符二元文法 +
纯标准库实现，零依赖、零 API、完全可复现，契合项目"确定性、可审计"原则；代价是
语义粒度较粗，仅能捕获极端内容失真，需后续以标注样本标定阈值或升级为本地 embedding。
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
    """Jaccard similarity of two strings' character-bigram sets, in [0, 1]."""
    A, B = char_bigrams(a), char_bigrams(b)
    if not A and not B:
        return 1.0
    if not A or not B:
        return 0.0
    inter = len(A & B)
    union = len(A | B)
    return inter / union if union else 0.0


class FaithfulnessChecker:
    """Deterministic content-faithfulness checker (optional verifier layer)."""

    def __init__(self, article_texts: dict, threshold: float = 0.15, min_len: int = 8):
        # Normalize keys to "law#article" strings.
        self.texts = {str(k): str(v) for k, v in (article_texts or {}).items()}
        self.threshold = float(threshold)
        self.min_len = int(min_len)

    @classmethod
    def load(cls, path: Path, threshold: float = 0.15, min_len: int = 8):
        p = Path(path)
        if not p.exists():
            return cls({}, threshold=threshold, min_len=min_len)
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return cls({}, threshold=threshold, min_len=min_len)
        texts = data.get("article_texts", data) if isinstance(data, dict) else {}
        return cls(texts, threshold=threshold, min_len=min_len)

    def key(self, law: str, article: int) -> str:
        return f"{law}#{article}"

    def text_for(self, law: str, article: int) -> str | None:
        return self.texts.get(self.key(law, article))

    def score(self, answer: str, law: str, article: int) -> float | None:
        """Similarity [0,1] of `answer` to the official text, or None if unavailable."""
        official = self.text_for(law, article)
        if not official:
            return None
        return jaccard(answer, official)

    def is_faithful(self, answer: str, law: str, article: int) -> bool | None:
        """True=faithful, False=unfaithful (✗F), None=skip (no official text / too short)."""
        official = self.text_for(law, article)
        if not official:
            return None
        if len(normalize_text(answer)) < self.min_len:
            return None
        return jaccard(answer, official) >= self.threshold
