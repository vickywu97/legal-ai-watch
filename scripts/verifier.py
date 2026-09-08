#!/usr/bin/env python3
"""
verifier.py — Legal AI Watch 确定性核验引擎 (本地 · 零依赖 · 可复现 · 可审计)

这是 Legal AI Watch 的**官方核验方法学** (见 docs/METHODOLOGY.md §7), 不再是
"bench 不可用时的兜底". 设计原则:

1. 引注归一化到 canonical 法条 provision
   - 法律名别名归一 (《中华人民共和国民法典》≡《民法典》)
   - 中文 / 阿拉伯数字统一 (第584条 ≡ 第五百八十四条)
   - 跨版本 / 跨法等价映射 (config/statute_equivalence.json):
     任何"同一规制对象"的不同条号 / 不同法名都映射到同一 canonical ID,
     故模型引旧条号 / 别名 / 姊妹法均判正确, 不再逐题手写 acceptable_citations.

2. 幻觉类型区分 (status)
   ✓    命中预期 (或等价) 引注
   ✗MA  引注与预期不符 (错引了真实存在但错误的法条)
   ✗T   引注已废止法律且非等价 (时序幻觉: 用已失效旧法作答)
   ✗NF  引注法条不存在 (NOT_FOUND: 条号超出该法已知有效条文范围, 即编造了不存在的法条)
   ·    未识别到法条引注 (nocite)
   ?    题目不可验证 / 无预期引注

3. 纯字符串规则, 不调用任何 LLM, 离线可跑, 结果完全可审计.
   如需接入外部知识库判重 (更严格的语义判重), 可在 verify() 外层包装,
   但默认方法学即本确定性引擎.

Usage (as a library):
  from verifier import Equivalence, verify
  eq = Equivalence.load(CONFIG_DIR / "statute_equivalence.json")
  result = verify(question, answer_text, eq)
"""
from __future__ import annotations

import json
import re
from pathlib import Path

# ----------------------------------------------------------------------------
# Low-level citation parsing / normalization
# ----------------------------------------------------------------------------
# Chinese: 《民法典》第584条 / 《刑法》第20条第2款
CITATION_RE = re.compile(
    r"《([^》]+)》\s*第\s*([0-9零一二三四五六七八九十百千]+)\s*条"
    r"(?:\s*第\s*([0-9零一二三四五六七八九十百千]+)\s*款)?"
)
# English: "Article 584 of the Civil Code" OR "Civil Code Article 584".
# The law name must end with Act/Code/Law so multi-word names (e.g.
# "Personal Information Protection Law") are captured whole.
EN_CITATION_RE = re.compile(
    r"(?:"
    r"(?:Article|Art\.?)\s*([0-9]+)\s+of\s+(?:the\s+)?([A-Za-z]+(?:\s+[A-Za-z]+)*?\s+(?:Act|Code|Law))\b"
    r"|"
    r"([A-Za-z]+(?:\s+[A-Za-z]+)*?\s+(?:Act|Code|Law))\s+(?:Article|Art\.?)\s*([0-9]+)"
    r")",
    re.IGNORECASE,
)
# Chinese government documents carry NO article number (they are notices, not
# codes): 国发〔2022〕8号 / 财税〔2016〕36号. The body is an explicit alternation
# of known issuing bodies (not a generic CJK run) so preceding context like
# "依据国发〔…〕" is NOT captured as "依据国发". Accepts fullwidth 〔〕 or halfwidth
# [] brackets (models occasionally mix them), and an optional 第 before the
# serial (国发〔2022〕第8号). Real law citations like 《民法典》第584条 (which have
# 《》第条) are never captured here.
GOV_DOC_RE = re.compile(
    r"(国发|国办发|财税|财政部|税务总局|国家税务总局|税总)\s*[〔\[]\s*(\d{4})\s*[〕\]]\s*(?:第)?\s*(\d+)\s*号"
)


def _parse_en(m) -> tuple:
    """Return (law_raw, article) from an English citation match, or (None, None)."""
    if m.group(1) is not None:  # form A: Article N of the <Law>
        return (m.group(2), int(m.group(1)))
    if m.group(3) is not None:  # form B: <Law> Article N
        return (m.group(3), int(m.group(4)))
    return (None, None)


def _en_law_to_cn(law_raw: str):
    """Map an English law-name fragment to a canonical Chinese short name, or None."""
    if not law_raw:
        return None
    s = law_raw.strip().lower()
    s = re.sub(r"^the\s+", "", s)
    return EN_LAW_ALIASES.get(s)

# Statuses that count as hallucination (used by leaderboard aggregation).
# The deterministic verifier emits ✗MA (wrong-but-existing article),
# ✗T (temporal/version hallucination), and ✗NF (NOT_FOUND: the cited article
# number falls outside the law's known valid range, i.e. the provision does not
# exist). Bare factual / content-faithfulness errors (✗F) are NOT produced —
# the verifier checks citation existence/validity + temporal validity, not
# substantive content. Keeping this set truthful prevents the leaderboard from
# implying finer-grained error classification than the engine actually delivers.
# NOTE: adding ✗NF to this set does NOT change HVI — it only relabels answers
# that were previously ✗MA (a non-existent article is still a hallucination),
# so total wrong-count is preserved.
HALLUCINATION_STATUSES = {"✗MA", "✗T", "✗NF"}

# Content-faithfulness (✗F) is an OPTIONAL, default-OFF enhancement layer
# (scripts/faithfulness.py). It is intentionally NOT in HALLUCINATION_STATUSES,
# so enabling it never changes HVI — it only downgrades a ✓ to ✗F when the cited
# article's content is judged unfaithful. See docs/XF_CONTENT_FAITHFULNESS_DESIGN.md.
FAITHFULNESS_FAIL = "✗F"

# Law-name canonicalization: official full title -> short name
LAW_NAME_ALIASES = {
    "中华人民共和国民法典": "民法典",
    "中华人民共和国刑法": "刑法",
    "中华人民共和国公司法": "公司法",
    "中华人民共和国个人所得税法": "个人所得税法",
    "中华人民共和国增值税法": "增值税法",
    "中华人民共和国增值税暂行条例": "增值税暂行条例",
    "中华人民共和国营业税暂行条例": "营业税暂行条例",
    "中华人民共和国营业税改征增值税试点实施办法": "营改增试点实施办法",
    "中华人民共和国专利法": "专利法",
    "中华人民共和国劳动合同法": "劳动合同法",
    "中华人民共和国合同法": "合同法",
    "中华人民共和国婚姻法": "婚姻法",
    "中华人民共和国继承法": "继承法",
    "中华人民共和国物权法": "物权法",
    "中华人民共和国担保法": "担保法",
    "中华人民共和国民法通则": "民法通则",
    "中华人民共和国侵权责任法": "侵权责任法",
    "中华人民共和国民法总则": "民法总则",
    "中华人民共和国数据安全法": "数据安全法",
    "中华人民共和国个人信息保护法": "个人信息保护法",
    "中华人民共和国行政处罚法": "行政处罚法",
    "中华人民共和国行政许可法": "行政许可法",
    "中华人民共和国反不正当竞争法": "反不正当竞争法",
}
# English law name -> canonical Chinese short name
EN_LAW_ALIASES = {
    "civil code": "民法典",
    "criminal law": "刑法",
    "company law": "公司法",
    "corporate law": "公司法",
    "personal income tax law": "个人所得税法",
    "value-added tax law": "增值税法",
    "patent law": "专利法",
    "labor contract law": "劳动合同法",
    "data security law": "数据安全法",
    "personal information protection law": "个人信息保护法",
    "pipl": "个人信息保护法",
    "anti-unfair-competition law": "反不正当竞争法",
}

_CN_NUM = {
    "零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
    "七": 7, "八": 8, "九": 9, "十": 10, "百": 100, "千": 1000,
}


def cn_to_int(s: str) -> int:
    """Convert a Chinese numeral (up to 9999) or arabic numeral string to int."""
    s = (s or "").strip()
    if s.isdigit():
        return int(s)
    total = 0
    current = 0
    for ch in s:
        if ch in ("十", "百", "千"):
            unit = _CN_NUM[ch]
            if current == 0:
                current = 1
            total += current * unit
            current = 0
        else:
            current = _CN_NUM.get(ch, 0)
    total += current
    return total


def normalize_law_name(name: str) -> str:
    n = (name or "").strip()
    n = re.sub(r"^中华人民共和国", "", n)
    n = LAW_NAME_ALIASES.get(n, n)
    n = re.sub(r"\s+", "", n)
    return n


def parse_ref(cite: str):
    """Parse a citation string into (law_short_name, article_int) or None."""
    if not cite:
        return None
    m = CITATION_RE.search(cite)
    if m:
        law = normalize_law_name(m.group(1))
        article = cn_to_int(m.group(2))
        return (law, article)
    # English form
    em = EN_CITATION_RE.search(cite)
    if em:
        law_raw, article = _parse_en(em)
        law = _en_law_to_cn(law_raw)
        return (law, article) if law else None
    # Government document (国务院/财税文件): no article number -> article=None.
    gm = GOV_DOC_RE.search(cite)
    if gm:
        doc_id = f"{gm.group(1)}〔{gm.group(2)}〕{gm.group(3)}号"
        return (doc_id, None)
    return None


def citation_key(cite: str) -> str:
    """Canonical key for a citation: '<law>#<article>' (article granularity)."""
    ref = parse_ref(cite)
    if ref is None:
        return normalize_law_name(cite or "")
    law, article = ref
    return f"{law}#{article}"


def extract_citations(text: str) -> list[str]:
    """Return a list of normalized citation strings found in `text`."""
    out = []
    for m in CITATION_RE.finditer(text or ""):
        law, article, clause = m.group(1), m.group(2), m.group(3)
        cite = f"《{law}》第{article}条"
        if clause:
            cite += f"第{clause}款"
        out.append(cite)
    for em in EN_CITATION_RE.finditer(text or ""):
        law_raw, article = _parse_en(em)
        law = _en_law_to_cn(law_raw)
        if law is None:
            continue
        out.append(f"《{law}》第{article}条")
    for gm in GOV_DOC_RE.finditer(text or ""):
        doc_id = f"{gm.group(1)}〔{gm.group(2)}〕{gm.group(3)}号"
        out.append(doc_id)
    return out


# ----------------------------------------------------------------------------
# Equivalence (canonical provision mapping)
# ----------------------------------------------------------------------------
class Equivalence:
    """Loads config/statute_equivalence.json and maps any citation to its
    canonical (law, article) provision."""

    def __init__(self, data: dict):
        self.raw = data
        self.repealed_laws = set(data.get("repealed_laws", []))
        # law short-name -> (min_article, max_article). Used for ✗NF (NOT_FOUND)
        # detection: a cited article outside [min, max] does not exist.
        self.article_ranges = {
            law: tuple(r) for law, r in data.get("article_ranges", {}).items()
            if isinstance(r, (list, tuple)) and len(r) == 2
        }
        self._map = {}  # (law, article) -> canonical (law, article)
        for g in data.get("provision_groups", []):
            cur = parse_ref(g["current"])
            if cur is None:
                continue
            for ref in [g["current"]] + list(g.get("equivalents", [])):
                k = parse_ref(ref)
                if k is not None:
                    self._map[k] = cur

    @classmethod
    def load(cls, path: Path):
        if not Path(path).exists():
            return cls({"provision_groups": [], "repealed_laws": []})
        with open(path, "r", encoding="utf-8") as f:
            return cls(json.load(f))

    def canonical(self, law: str, article: int):
        return self._map.get((law, article), (law, article))

    def is_repealed_law(self, law: str) -> bool:
        return law in self.repealed_laws

    def canonical_key(self, cite: str) -> str:
        ref = parse_ref(cite)
        if ref is None:
            return normalize_law_name(cite or "")
        law, article = self.canonical(*ref)
        return f"{law}#{article}"


# ----------------------------------------------------------------------------
# Verification
# ----------------------------------------------------------------------------
def verify(question: dict, answer: str, eq: Equivalence, faithfulness=None) -> dict:
    """Verify a single model `answer` against `question` using equivalence `eq`.

    Returns a dict with at minimum: {status, detail, citations}.
    Status is one of ✓ / ✗MA / ✗T / ✗NF / ✗F / · / ?.

    `faithfulness` (optional, scripts/faithfulness.FaithfulnessChecker): when
    provided, a ✓ verdict whose cited article content is judged unfaithful is
    downgraded to ✗F. Disabled by default; never affects HVI.
    """
    citations = extract_citations(answer)
    verifiable = question.get("verifiable", True)
    expected = question.get("expected_citation", "")

    if not citations:
        return {"status": "·", "detail": "未识别到法条引注", "citations": []}

    if not verifiable or not expected:
        # Cannot judge against a knowledge base; do not penalize.
        return {"status": "?", "detail": "无法判定（题目不可验证或无预期引注）",
                "citations": citations}

    exp_ref = parse_ref(expected)
    if exp_ref is None:
        return {"status": "?", "detail": f"预期引注无法解析: {expected}", "citations": citations}
    exp_law, exp_art = exp_ref
    exp_canon = eq.canonical(exp_law, exp_art)

    def _emit_ok(detail: str, cite: str) -> dict:
        # Optional content-faithfulness downgrade (✗F). Only fires on the ✓ path
        # and only when an official article text is available for the cited
        # provision; otherwise the verdict stays ✓ (no false ✗F on uncovered laws).
        if faithfulness is not None and cite:
            ref = parse_ref(cite)
            if ref is not None:
                law, art = eq.canonical(*ref)
                ok = faithfulness.is_faithful(answer, law, art)
                if ok is False:
                    sc = None
                    try:
                        sc = faithfulness.score(answer, law, art)
                    except Exception:
                        pass
                    return {"status": FAITHFULNESS_FAIL,
                            "detail": f"引注条号正确但内容表述不忠实 (Faithfulness fail): {cite}",
                            "citations": citations,
                            "faithfulness_checked": True,
                            "faithfulness_score": sc}
                # ok is True: faithful pass → ✓, but record that we checked.
                if ok is True:
                    return {"status": "✓", "detail": detail, "citations": citations,
                            "faithfulness_checked": True}
        return {"status": "✓", "detail": detail, "citations": citations}

    matched_canonical = None
    matched_alt = None
    temporal_hit = None  # cited a repealed-law provision that is NOT equivalent
    for c in citations:
        ref = parse_ref(c)
        if ref is None:
            continue
        law, art = ref
        canon = eq.canonical(law, art)
        if canon == exp_canon:
            matched_canonical = c
            break
        # temporal: cited a repealed law, and it is NOT the expected provision
        if eq.is_repealed_law(law) and canon != exp_canon:
            temporal_hit = c

    if matched_canonical is not None:
        return _emit_ok(f"命中预期引注 {expected}", matched_canonical)

    # Per-question override (kept for backward compatibility / one-off cases):
    # accepts provisions that map to the SAME canonical provision as expected
    # (cross-version / cross-law equivalence). It CANNOT accept a *different but
    # equally correct* article — that is what `also_correct` below is for.
    # IMPORTANT: an acceptable citation only counts if the model ACTUALLY cited
    # it (or a provision canonicalizing to it). Otherwise any wrong citation on a
    # question that merely *has* an acceptable_citation would be wrongly passed.
    for alt in (question.get("acceptable_citations") or []):
        alt_cite = alt.get("citation", "") if isinstance(alt, dict) else str(alt)
        ref = parse_ref(alt_cite)
        if ref is None:
            continue
        alt_canon = eq.canonical(*ref)
        if alt_canon != exp_canon:
            continue
        for c in citations:
            cref = parse_ref(c)
            if cref is not None and eq.canonical(*cref) == alt_canon:
                just = alt.get("justification", "") if isinstance(alt, dict) else ""
                return _emit_ok(
                    f"命中可接受等价引注 {alt_cite}（等价性论证：{just}）", c)

    # Distinct-but-also-correct provisions: a model may cite a DIFFERENT article
    # that is nonetheless legally correct (e.g. 违约责任一般规定 vs 损害赔偿
    # 特别规定). Accepting these prevents FALSE ✗MA, which would otherwise inflate
    # HVI and misrepresent the model. This is an accuracy-safeguard, not a loophole:
    # every entry is curated and must survive the lawyer verification gate.
    for alt in (question.get("also_correct") or []):
        alt_cite = alt.get("citation", "") if isinstance(alt, dict) else str(alt)
        ref = parse_ref(alt_cite)
        if ref is None:
            continue
        alt_canon = eq.canonical(*ref)
        for c in citations:
            cref = parse_ref(c)
            if cref is not None and eq.canonical(*cref) == alt_canon:
                just = alt.get("justification", "") if isinstance(alt, dict) else ""
                return _emit_ok(
                    f"命中同样正确的引注 {alt_cite}（同样正确：{just}）", c)

    if temporal_hit is not None:
        return {"status": "✗T",
                "detail": f"引注已废止法律（时序幻觉）: {temporal_hit}（预期 {expected}）",
                "citations": citations}

    # NOT_FOUND (✗NF): a cited CURRENT-law article whose number is outside that
    # law's known valid range -> the provision does not exist (made-up article).
    # This separates "编造不存在的法条" (✗NF) from "引了真实但错误的法条" (✗MA).
    # Repealed-law citations are caught above as ✗T and never reach here. Laws
    # absent from article_ranges are left as ✗MA (conservative: without a corpus
    # we cannot assert non-existence, so we avoid false ✗NF).
    for c in citations:
        ref = parse_ref(c)
        if ref is None:
            continue
        law, art = ref
        rng = eq.article_ranges.get(law)
        if rng is not None and not (rng[0] <= art <= rng[1]):
            return {"status": "✗NF",
                    "detail": (f"引注法条不存在 (NOT_FOUND): {c}"
                               f"（{law} 有效条文范围为第{rng[0]}–{rng[1]}条）"),
                    "citations": citations}

    return {"status": "✗MA",
            "detail": f"引注与预期不符 (期望 {expected}, 实际 {citations[0]})",
            "citations": citations}


# ----------------------------------------------------------------------------
# Answer-level hallucination detectors (v1.3: 编造判例 / 循环引注 / 自相矛盾)
# ----------------------------------------------------------------------------
# These mirror the semantics of bench/answer_checks.py but run on watch's OWN
# extracted citations + answer text. watch's verifier is intentionally
# self-contained (docs/METHODOLOGY.md §7: "核验质量=产品本身"), so the same
# answer-level logic lives here rather than as a submodule import. Every
# detector attaches an `answer_flags` dict to each verification and NEVER
# changes HVI — the citation-level status remains the single source of truth
# for the leaderboard's hallucination rate.
GUIDING_CASE_RE = re.compile(r"指导?性?案例\s*第?\s*(\d+)\s*号")
_GUIDING_CASES: "set|None" = None


def load_guiding_cases(path: "Path|None" = None) -> set:
    """Load the verified guiding-case registry as a set of ints (guide_no).

    Mirrors bench/knowledge_base/cases.json (kept in sync by hand; the two
    registries are the same curated set). Returns an empty set if the file is
    absent so the detector degrades to "everything is fabricated" only when
    misconfigured — callers should ensure the registry exists.
    """
    global _GUIDING_CASES
    if _GUIDING_CASES is not None:
        return _GUIDING_CASES
    p = path or (Path(__file__).resolve().parent.parent / "config" / "guiding_cases.json")
    if not Path(p).exists():
        _GUIDING_CASES = set()
        return _GUIDING_CASES
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    _GUIDING_CASES = {int(c["guide_no"]) for c in data.get("cases", [])}
    return _GUIDING_CASES


def extract_guiding_cases(text: str) -> list:
    return [int(m.group(1)) for m in GUIDING_CASE_RE.finditer(text or "")]


def detect_fabricated_case(answer: str, registry: set | None = None):
    """Return (is_fabricated, [fabricated_numbers], [all_cited_numbers]).

    A guiding case (指导案例第N号) is a real-world factual claim; we verify it
    against the curated registry. A cited number outside the registry is a
    HARD fabricated-case hallucination (the benchmark's "guiding-case HR").
    """
    if registry is None:
        registry = load_guiding_cases()
    found = extract_guiding_cases(answer)
    fabricated = [n for n in found if n not in registry]
    return bool(fabricated), fabricated, found


_CIRC_REF_RE = re.compile(r"第\s*([0-9零一二三四五六七八九十百千]+)\s*条")


def detect_circular_citation(answer: str):
    """Return (is_circular, [all_provision_numbers]).

    Heuristic: detect a provision cycle referenced within the answer's OWN
    reasoning — e.g. "依据第15条，而第15条又引第16条，第16条复引第15条". Real
    statutes form a DAG, so a self-referential cycle is pathological. This is an
    EXPERIMENTAL answer-level signal (documented as such); it targets the
    reasoning trap, not a KB graph, so it stays self-contained.
    """
    nums = [cn_to_int(m.group(1)) for m in _CIRC_REF_RE.finditer(answer or "")]
    seen: dict = {}
    for i, n in enumerate(nums):
        if n in seen and (i - seen[n] > 1):
            return True, nums
        seen[n] = i
    if re.search(r"(互为援引|循环引用|循环引注|互相引用|相互引用)", answer or ""):
        return True, nums
    return False, nums


# Self-contradiction (diagnostic ONLY — never a hallucination verdict).
# Ordered list of (positive, negative) predicate pairs (NOT a dict: dict would
# collapse duplicate keys like "应当" which legitimately maps to BOTH "无需" and
# "不得").
_OPP = [
    ("有效", "无效"), ("无效", "有效"),
    ("成立", "不成立"), ("不成立", "成立"),
    ("属于", "不属于"), ("不属于", "属于"),
    ("承担", "不承担"), ("不承担", "承担"),
    ("应当", "无需"), ("必须", "无需"),
    ("应当", "不得"), ("必须", "不得"),
]
_CLAUSE_SPLIT = re.compile(r"[。；;！？\n]")


def _shared_head(a: str, b: str) -> bool:
    """Crude shared 'head' check: any >=3-char Chinese substring common to both
    clauses (a real shared subject). Good enough for a diagnostic flag."""
    for n in range(3, min(len(a), len(b)) + 1):
        for s in range(0, len(a) - n + 1):
            sub = a[s:s + n]
            if sub in b and re.search(r"[一-鿿]", sub):
                return True
    return False


def _clause_pair_contradicts(a: str, b: str) -> bool:
    for pos, neg in _OPP:
        if pos in a and neg in b and _shared_head(a, b):
            return True
        if neg in a and pos in b and _shared_head(a, b):
            return True
    return False


def detect_self_contradiction(text: str) -> bool:
    """Heuristic self-contradiction flag (DIAGNOSTIC ONLY, not scored).

    Flags when the same legal head is asserted with opposing predicates across
    clauses, or an explicit reversal negates an earlier claim about the same
    head without resolution. Returns True as a soft signal requiring expert
    confirmation — the pipeline treats it as such and never penalizes HVI.
    """
    if not text:
        return False
    clauses = [c.strip() for c in _CLAUSE_SPLIT.split(text) if c.strip()]
    for i in range(len(clauses)):
        for j in range(i + 1, len(clauses)):
            if _clause_pair_contradicts(clauses[i], clauses[j]):
                return True
    return False


def answer_level_flags(answer: str, registry: set | None = None) -> dict:
    """Compute all three answer-level flags for one answer (cheap, offline)."""
    fab, fab_list, cited = detect_fabricated_case(answer, registry)
    circ, _ = detect_circular_citation(answer)
    sc = detect_self_contradiction(answer)
    return {
        "fabricated_case": fab,
        "fabricated_cases": fab_list,
        "cited_guiding_case": bool(cited),
        "circular": circ,
        "self_contradiction": sc,
    }
