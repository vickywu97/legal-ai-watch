#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""coverage_report.py — 基准覆盖诊断 (离线, 仅标准库).

用途
----
把 legal-ai-watch 每道题的引注 (expected_citation / also_correct / acceptable_citations)
逐一映射到 ``config/article_texts.json`` 的参考库 (键 ``law#article``), 产出:

1. 每题引注覆盖状态 (是否全部命中已核验参考文本);
2. 未被任何题目引用的 *已核验* 参考条文 (扩展题库的安全锚点);
3. 领域 / 法条分布;
4. 待补参考缺口 (题目预期引注但参考库无对应全文).

等价引注由 ``config/statute_equivalence.json`` 归一化 (旧条号 / 别名 / 姊妹法
均映射到现行 canonical 键), 避免把"条号版本差异"误报为缺口。

本脚本只读不改, 不写任何文件, 输出到 stdout。可直接纳入 CI 作为"覆盖门禁"的
离线预览 (正式门禁在 .github/workflows/ci.yml 的 article_texts 不变量里)。
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


def load_json(name):
    with open(CONFIG_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)


def build_equiv_index(eq: dict) -> dict:
    """Return {normalized_citation_str: canonical_key} using provision_groups."""
    idx = {}
    for grp in eq.get("provision_groups", []):
        cur = grp.get("current")
        if not cur:
            continue
        canon = _ref_to_key(cur)
        if not canon:
            continue
        for form in [cur] + list(grp.get("equivalents", [])):
            k = _ref_to_key(form)
            if k:
                idx[k] = canon
        idx[canon] = canon
    return idx


def _ref_to_key(ref: str):
    """'《民法典》第584条' -> '民法典#584' (用 verifier.parse_ref 归一化)。"""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from verifier import parse_ref
        law, art = parse_ref(ref)
        if law and isinstance(art, int):
            return f"{law}#{art}"
    except Exception:
        pass
    return None


def main() -> int:
    questions = load_json("questions.json")["questions"]
    article_texts = load_json("article_texts.json")["article_texts"]
    try:
        eq = load_json("statute_equivalence.json")
    except FileNotFoundError:
        eq = {}
    equiv_idx = build_equiv_index(eq)

    present_keys = set(article_texts.keys())
    used_keys = set()
    q_coverage = []
    uncovered_expected = []

    for q in questions:
        cites = []
        ec = q.get("expected_citation")
        if ec:
            cites.append(("expected", ec))
        for ac in q.get("also_correct", []) or []:
            if ac.get("citation"):
                cites.append(("also_correct", ac["citation"]))
        for ac in q.get("acceptable_citations", []) or []:
            if ac.get("citation"):
                cites.append(("acceptable", ac["citation"]))

        covered = []
        missing = []
        for kind, ref in cites:
            key = _ref_to_key(ref)
            if key and key in present_keys:
                covered.append((kind, ref, key))
                used_keys.add(key)
            elif key and key in equiv_idx and equiv_idx[key] in present_keys:
                canon = equiv_idx[key]
                covered.append((kind, ref, f"{canon} (等价)"))
                used_keys.add(canon)
            else:
                missing.append((kind, ref, key))
        if missing:
            uncovered_expected.extend([(q["qid"], kind, ref, key) for kind, ref, key in missing])
        q_coverage.append({
            "qid": q["qid"],
            "domain": q.get("domain", "?"),
            "expected": ec,
            "covered": len(covered),
            "missing": len(missing),
        })

    unused = sorted(present_keys - used_keys)

    print("=" * 72)
    print(f"基准覆盖诊断  | 题目 {len(questions)} 道 | 参考库 {len(present_keys)} 条")
    print("=" * 72)

    print("\n[1] 题目引注覆盖")
    bad = [r for r in q_coverage if r["missing"] > 0]
    print(f"    全部命中: {len(q_coverage) - len(bad)} / {len(q_coverage)}")
    if bad:
        print(f"    存在未覆盖引注的题目 ({len(bad)}):")
        for r in bad:
            print(f"      Q{r['qid']:>2} [{r['domain']}] expected={r['expected']}")
            for qid, kind, ref, key in uncovered_expected:
                if qid == r["qid"]:
                    print(f"           - {kind}: {ref}  -> key={key}")

    print("\n[2] 未被任何题目引用的已核验参考条文 (扩展安全锚点)")
    print(f"    共 {len(unused)} 条:")
    for k in unused:
        print(f"      - {k}")

    print("\n[3] 待补参考缺口 (题目预期引注但参考库无全文)")
    if uncovered_expected:
        for qid, kind, ref, key in uncovered_expected:
            print(f"      Q{qid} {kind}: {ref}  -> key={key}")
    else:
        print("      无 (所有题目引注均有对应参考全文)")

    print("\n[4] 领域分布")
    dom = Counter(q.get("domain", "?") for q in questions)
    for k, v in dom.most_common():
        print(f"      {k}: {v}")

    print("\n[5] 法条分布 (按已命中参考键的法名)")
    law_ct = Counter(k.split("#")[0] for k in used_keys)
    for k, v in sorted(law_ct.items()):
        print(f"      {k}: {v}")

    print("\n[6] 扩展容量小结")
    print(f"     已用参考 {len(used_keys)} / {len(present_keys)} | 可用锚点 {len(unused)}")
    print(f"     若全部锚点出题, 理论可扩至约 {len(questions) + len(unused)} 道 (同领域可复用)")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
