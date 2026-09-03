#!/usr/bin/env python3
"""
build_article_texts.py — 从 LHB 已核验全文本 KB 生成 legal-ai-watch 的 config/article_texts.json

设计铁律（对法律准确性基准至关重要）：
  本脚本【只】从 legal-hallucination-bench 的
  knowledge_base/laws/statutes.jsonl（2327 条，verification_status 全为 verified，
  逐条来自全国人大 / 中国政府网官方文本）抽取法条正文。
  绝不凭模型记忆生成任何法条文字——那正是本基准要检测的幻觉。
  KB 未覆盖的规范一律留空、写入 _uncovered 清单，交由人工补充官方原文。

幂等性：
  - 对每道题目的全部合法引注（预期解 + 备选正确解），经 verifier 同款 parse_ref 归一化；
  - 能在 KB 命中 → 写官方【全文】；
  - 命中不到、但既有 article_texts.json 里有人工核验过的正文 → 保留（不静默覆盖）；
  - 都命中不到 → 进 _uncovered，不写内容。
  重跑结果稳定（KB 与 questions.json 不变则产物不变）。

复用 verifier 的归一化逻辑，保证 article_texts 的键名与运行时完全一致。

用法：
  # 默认：自动探测 LHB 的 statutes.jsonl，就地更新 config/article_texts.json
  python scripts/build_article_texts.py

  # 只预览、不写文件
  python scripts/build_article_texts.py --dry-run

  # 显式指定 KB（当 LHB 不在默认探测路径时）
  python scripts/build_article_texts.py --kb /path/to/statutes.jsonl

范围外规范（LHB 8 部法 KB 未覆盖）的「人工核验官方原文」工作流：
  # 1) 生成/更新留空模板（幂等，保留已填正文）
  python scripts/build_article_texts.py --emit-pending config/article_texts_unverified.json
  # 2) 律师逐条从官方原文核对填入 article_texts[*]，并把 _pending[*].status 置 VERIFIED
  # 3) 合并进主库（仅接受 VERIFIED 且正文非空者；主库 _uncovered 同步移除）
  python scripts/build_article_texts.py --merge-pending config/article_texts_unverified.json
"""
import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional, Tuple

# ── 路径解析 ────────────────────────────────────────────────────────────────
# 脚本位于 <repo>/scripts/ 下，repo 根为 scripts 的父目录。
REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
QUESTIONS_DEFAULT = REPO_ROOT / "config" / "questions.json"
TARGET_DEFAULT = REPO_ROOT / "config" / "article_texts.json"

# LHB 已核验 KB 的候选探测路径（按优先级）：
#   1. 与 legal-ai-watch 同级的 legal-hallucination-bench（本机工作区常见布局）
#   2. 本机 WorkBuddy 下的若干历史工作区
#   3. 环境变量 WORKBUDDY_LHB_KB
KB_CANDIDATES = [
    REPO_ROOT.parent / "legal-hallucination-bench" / "knowledge_base" / "laws" / "statutes.jsonl",
    Path("/Users/vickywu/WorkBuddy/2026-07-26-16-50-27/legal-hallucination-bench/knowledge_base/laws/statutes.jsonl"),
]

# LHB law_code -> legal-ai-watch 归一化后的 canonical 短名（与 verifier 一致）
LAW_CODE_TO_CN = {
    "CIVIL_CODE": "民法典",
    "CRIMINAL_LAW": "刑法",
    "COMPANY_LAW": "公司法",
    "TAX_ADMIN_LAW": "税收征管法",
    "PATENT_LAW": "专利法",
    "EIT_LAW": "企业所得税法",
    "VAT_LAW": "增值税法",
    "IIT_LAW": "个人所得税法",
}

ART_RE = re.compile(r"^第(\d+)条$")                       # 第162条   -> 162
ART_SUB_RE = re.compile(r"^第(\d+)条之[一二三四五六七八九十]+$")  # 第162条之二 -> 162

# 范围外规范（不在 LHB 8 部法 KB 内）的官方出处指引。
# 注意：此处只给「权威发布机构 + 检索路径」，【绝不】提供任何条文正文——
# 正文须由人工（律师）从官方原文逐条核对填入，否则正是本基准要检测的幻觉。
# 令号/施行日期为公开已知信息，仍建议填入时于官方库二次核对。
OFFICIAL_SOURCE = {
    "个人信息保护法": (
        "全国人大常委会公布（主席令第六十一号，2021-08-20 通过，2021-11-01 施行）。"
        "权威文本：国家法律法规数据库 https://flk.npc.gov.cn 或 中国政府网 https://www.gov.cn"
    ),
    "数据安全法": (
        "全国人大常委会公布（主席令第八十四号，2021-06-10 通过，2021-09-01 施行）。"
        "权威文本：国家法律法规数据库 https://flk.npc.gov.cn 或 中国政府网 https://www.gov.cn"
    ),
    "反不正当竞争法": (
        "全国人大常委会公布（2025修订，2025-10-15 施行；2025修订将“混淆行为”由旧法第6条移至第7条，"
        "第6条改为“社会监督”）。权威文本：国家法律法规数据库 https://flk.npc.gov.cn 或 中国政府网 https://www.gov.cn"
    ),
    "个人所得税专项附加扣除暂行办法": (
        "国务院规范性文件（国发〔2018〕41号，2018-12-13 印发，2019-01-01 施行），"
        "中国政府网 https://www.gov.cn 全文公布。"
    ),
}


def norm_text(s: str) -> str:
    """粗归一化用于比对（去标点空白）。"""
    return re.sub(r"[\s，。、；：？！\"'（）()《》〈〉【】—…·　]", "", s or "")


def resolve_kb_path(explicit: Optional[str]) -> Path:
    if explicit:
        p = Path(explicit).expanduser()
        if not p.exists():
            sys.exit(f"[error] --kb 指定路径不存在: {p}")
        return p
    import os
    env = os.environ.get("WORKBUDDY_LHB_KB")
    if env and Path(env).exists():
        return Path(env)
    for cand in KB_CANDIDATES:
        if cand.exists():
            return cand
    sys.exit(
        "[error] 未找到 LHB 的 statutes.jsonl。请通过 --kb /path/to/statutes.jsonl "
        "显式指定，或设置环境变量 WORKBUDDY_LHB_KB。"
    )


def load_kb(path: Path) -> dict:
    """返回 {(law_cn, article_int): content}，优先精确「第N条」，之X 变体兜底。"""
    kb: dict = {}
    sub: dict = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        if r.get("verification_status") != "verified":
            continue  # 只信任已核验条目
        cn = LAW_CODE_TO_CN.get(r.get("law_code"))
        if not cn:
            continue
        an = r.get("article_number", "")
        m = ART_RE.match(an)
        if m:
            kb[(cn, int(m.group(1)))] = r.get("content", "")
            continue
        m = ART_SUB_RE.match(an)
        if m:
            sub.setdefault((cn, int(m.group(1))), r.get("content", ""))
    for k, v in sub.items():
        kb.setdefault(k, v)
    return kb


def needed_pairs(questions: Path) -> Tuple[dict, list, int]:
    """39 题引用到的全部合法法条，经 verifier 同款 parse_ref 归一化。"""
    sys.path.insert(0, str(SCRIPTS_DIR))
    from verifier import parse_ref  # noqa: E402  (延迟导入，避免无 scripts 时崩溃)
    data = json.loads(questions.read_text(encoding="utf-8"))
    qs = data["questions"]
    pairs: dict = {}
    unparsed: list = []
    for q in qs:
        cites = [("expected", q.get("expected_citation"))]
        for a in q.get("also_correct") or []:
            cites.append(("also", a.get("citation")))
        for kind, c in cites:
            ref = parse_ref(c or "")
            if not ref:
                unparsed.append((q["qid"], c))
                continue
            law, art = ref
            if art is None:
                unparsed.append((q["qid"], c))  # 政府文件（无条号），✗F 不适用
                continue
            pairs.setdefault((law, art), []).append((q["qid"], kind))
    return pairs, unparsed, len(qs)


def build(kb: dict, pairs: dict, old_texts: dict) -> Tuple[dict, list, list]:
    out: dict = {}
    covered: list = []
    uncovered: list = []
    for (law, art), hits in sorted(pairs.items()):
        key = f"{law}#{art}"
        if (law, art) in kb:
            covered.append(key)
            out[key] = kb[(law, art)]
        elif key in old_texts:
            covered.append(key)
            out[key] = old_texts[key]  # 保留用户已人工核验的种子
        else:
            uncovered.append({"key": key, "cited_by": [f"Q{h[0]}({h[1]})" for h in hits]})

    # 与既有种子比对：KB 优先于旧的节选 / 旧法种子，报告被替换项
    diffs: list = []
    for key, txt in old_texts.items():
        m = re.match(r"^(.+)#(\d+)$", key)
        if not m:
            continue
        law, art = m.group(1), int(m.group(2))
        if (law, art) in kb and norm_text(kb[(law, art)]) != norm_text(txt):
            diffs.append((key, len(txt), len(kb[(law, art)])))

    # containment 对参考长度不敏感 → 直接用官方全文，KB 未覆盖的法条保留原种子
    merged = dict(out)
    for k, v in old_texts.items():
        merged.setdefault(k, v)

    def sort_key(k):
        m = re.match(r"^(.+)#(\d+)$", k)
        return (m.group(1), int(m.group(2))) if m else (k, 0)
    merged = {k: merged[k] for k in sorted(merged, key=sort_key)}
    return merged, covered, uncovered, diffs, len(pairs)


def emit_pending(pending_path: Path, questions: Path, kb_path: Path) -> None:
    """生成/更新「人工核验官方原文」模板（幂等：保留已填正文）。

    模板正文全部留空，绝不代写法条——由律师从官方原文逐条核对填入。
    每条附：被哪些题引用(cited_by)、官方出处指引(official_source)、核验状态(status)。
    """
    kb = load_kb(kb_path)
    pairs, _unparsed, nq = needed_pairs(questions)
    _merged, _cov, uncovered, _diffs, npairs = build(kb, pairs, {})

    existing = json.loads(pending_path.read_text(encoding="utf-8")) if pending_path.exists() else {}
    old_pending = {p["key"]: p for p in existing.get("_pending", [])}
    old_texts = existing.get("article_texts", {})

    article_texts: dict = {}
    pending: list = []
    for u in uncovered:
        key = u["key"]
        law, art = key.split("#")
        prev_text = old_texts.get(key, "")
        article_texts[key] = prev_text
        meta = old_pending.get(key, {})
        pending.append({
            "key": key,
            "law": law,
            "article": int(art),
            "cited_by": u["cited_by"],
            "official_source": OFFICIAL_SOURCE.get(law, "请核对官方公布文本（全国人大 / 国务院 / 中国政府网）"),
            "status": meta.get("status", "PENDING_HUMAN_VERIFICATION"),
            "filled_text_len": len(prev_text or ""),
        })

    result = {
        "_NOTE": (
            "【人工核验模板，非运行数据】内容忠实度(✗F) 对 KB 未覆盖的范围外规范，"
            "需由人工从官方原文逐条核对填入正文，再经 --merge-pending 合并进主库 "
            "config/article_texts.json。本文件正文【必须】由律师核验填入，"
            "脚本绝不代写任何法条文字（那正是本基准要检测的幻觉）。\n"
            "填法：1) 在 article_texts 的对应键填入该条官方【全文】；"
            "2) 把 _pending 中该条的 status 改为 VERIFIED；"
            "3) 运行 python scripts/build_article_texts.py --merge-pending <本文件>。"
        ),
        "_source": {
            "generated_by": "scripts/build_article_texts.py --emit-pending",
            "derived_from": "config/questions.json 的全部引注 - LHB 已核验 KB",
            "official_source_guidance": "见各条 official_source 字段（权威发布机构 + 检索路径）",
        },
        "article_texts": article_texts,
        "_pending": pending,
    }
    pending_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[emit-pending] 写出模板 {pending_path}：{len(pending)} 条缺口待人工核验")
    print(f"                （{sum(1 for p in pending if p['filled_text_len']>0)} 条已填，"
          f"{sum(1 for p in pending if p['status']=='VERIFIED')} 条已标记 VERIFIED）")


def merge_pending(pending_path: Path, target_path: Path) -> None:
    """把模板中 status=VERIFIED 且正文非空的条目合并进主库 article_texts.json。

    安全闸：仅合并显式标记 VERIFIED 的条目；未核验（或仅填了字但未置 VERIFIED）
    的条目跳过并打印警告，避免把未核实文字当作官方标准答案。
    合并后主库 _uncovered 同步移除，模板中该条置为 MERGED 并清空正文。
    """
    p = json.loads(pending_path.read_text(encoding="utf-8"))
    pt = p.get("article_texts", {})
    pmeta = {m["key"]: m for m in p.get("_pending", [])}

    target = json.loads(target_path.read_text(encoding="utf-8"))
    at = target.setdefault("article_texts", {})

    merged_keys: list = []
    skipped: list = []
    for key, text in pt.items():
        meta = pmeta.get(key, {})
        status = meta.get("status")
        if not text or not text.strip():
            continue
        if status != "VERIFIED":
            skipped.append((key, status or "未标记 VERIFIED"))
            continue
        at[key] = text.strip()
        merged_keys.append(key)

    # 主库 _uncovered 同步移除已合并条目
    new_unc = [u for u in target.get("_uncovered", []) if u["key"] not in set(merged_keys)]
    target["_uncovered"] = new_unc
    target_path.write_text(json.dumps(target, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # 模板：合并项置 MERGED 并清空正文，未核验项保留以便后续继续填
    for m in p.get("_pending", []):
        if m["key"] in set(merged_keys):
            m["status"] = "MERGED"
    p["article_texts"] = {k: ("" if k in set(merged_keys) else v) for k, v in pt.items()}
    pending_path.write_text(json.dumps(p, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"[merge-pending] 已合并 {len(merged_keys)} 条 VERIFIED 条目 -> {target_path}")
    for k in merged_keys:
        print(f"                + {k}")
    if skipped:
        print(f"[merge-pending] 跳过 {len(skipped)} 条（已填但未标记 VERIFIED，需人工核验后重试）：")
        for k, s in skipped:
            print(f"                - {k} ({s})")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kb", help="LHB statutes.jsonl 路径（默认自动探测，见脚本顶部 KB_CANDIDATES）")
    ap.add_argument("--questions", type=Path, default=QUESTIONS_DEFAULT,
                    help=f"题目文件（默认 {QUESTIONS_DEFAULT}）")
    ap.add_argument("--out", type=Path, default=TARGET_DEFAULT,
                    help=f"输出 article_texts.json（默认 {TARGET_DEFAULT}）")
    ap.add_argument("--dry-run", action="store_true",
                    help="只打印覆盖/缺口报告，不写入文件")
    ap.add_argument("--emit-pending", type=Path, metavar="PATH",
                    help="生成/更新「人工核验官方原文」模板（正文留空，幂等保留已填内容）")
    ap.add_argument("--merge-pending", type=Path, metavar="PATH",
                    help="将模板中 status=VERIFIED 且正文非空的条目合并进主库 article_texts.json")
    args = ap.parse_args()

    # ── 模板工作流先于常规生成 ─────────────────────────────────────────────
    if args.emit_pending:
        kb_path = resolve_kb_path(args.kb)
        emit_pending(args.emit_pending, args.questions, kb_path)
        return
    if args.merge_pending:
        merge_pending(args.merge_pending, args.out)
        return

    kb_path = resolve_kb_path(args.kb)
    kb = load_kb(kb_path)
    pairs, _unparsed, nq = needed_pairs(args.questions)

    existing = json.loads(args.out.read_text(encoding="utf-8")) if args.out.exists() else {}
    old_texts = existing.get("article_texts", {})

    merged, covered, uncovered, diffs, npairs = build(kb, pairs, old_texts)

    print(f"[kb]    {kb_path}")
    print(f"[kb]    loaded {len(kb)} verified official articles from statutes.jsonl")
    print(f"[need]  {nq} questions -> {npairs} distinct (law, article) pairs")
    print(f"[cover] {len(covered)}/{npairs} pairs have official text")
    print(f"[gap]   {len(uncovered)} pairs WITHOUT official text (need user-supplied source)")
    for u in uncovered:
        cited = ", ".join(u["cited_by"][:4]) + (" …" if len(u["cited_by"]) > 4 else "")
        print(f"        - {u['key']}  cited by {cited}")
    if diffs:
        print(f"[fix]   {len(diffs)} seed entries replaced with KB full official text:")
        for key, a, b in diffs:
            print(f"          {key}: {a}字(节选/旧法) -> {b}字(官方全文)")
    else:
        print("[check] all seed entries already match KB official text ✓")

    if args.dry_run:
        print(f"\n[dry-run] 不会写入 {args.out}（将含 {len(merged)} 条 article_texts）")
        return

    result = {
        "_NOTE": (
            "内容忠实度(✗F) 校验用的官方法条【全文】正文。键为 'law#article'（与 "
            "verifier 归一化后的 canonical 形式一致，见 scripts/verifier.py）。"
            "正文由 scripts/build_article_texts.py 从 legal-hallucination-bench 的 "
            "knowledge_base/laws/statutes.jsonl 抽取生成（2327 条，verification_status 全为 "
            "verified，逐条取自全国人大/中国政府网官方文本），不凭记忆撰写任何条文。"
            "KB 未覆盖的法条 checker 自动跳过（不判 ✗F），缺口清单见 _uncovered。"
            "✗F 默认指标为 containment（|A∩B|/|A|），对参考文本长度不敏感，故此处使用完整条文；"
            "阈值标定见 docs/XF_CONTENT_FAITHFULNESS_DESIGN.md。"
        ),
        "_source": {
            "generated_by": "scripts/build_article_texts.py",
            "kb": "legal-hallucination-bench/knowledge_base/laws/statutes.jsonl",
            "kb_rows": 2327,
            "kb_verification_status": "verified (100%)",
            "law_code_map": LAW_CODE_TO_CN,
        },
        "_uncovered": uncovered,
        "article_texts": merged,
    }
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n[write] {args.out}  ({len(merged)} article texts, was {len(old_texts)})")


if __name__ == "__main__":
    main()
