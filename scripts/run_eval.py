#!/usr/bin/env python3
"""
run_eval.py — Legal AI Watch 主评测脚本

流程: 对 config/models.json 中的每个启用模型, 调用其 OpenAI 兼容聊天接口,
     抽取回答中的法条引注, 使用核验引擎(legal-hallucination-bench, 若以
     submodule 引入) 或本地兜底核验器逐条判定, 产出:
        data/answers/YYYY-MM-DD/answers.jsonl
        data/answers/YYYY-MM-DD/verifications.jsonl
        data/answers/YYYY-MM-DD/leaderboard.json
     并将本轮排行榜追加写入 data/leaderboard_history.json.

设计原则:
  - 与 bench 解耦: 若 bench submodule / 已安装包可用, 优先委托其 verify();
    否则使用本文件的本地兜底核验器 (仅用于演示与离线开发, 不应用于正式发布).
  - 零外部状态: 所有产物均为文件, 可复现.

Usage:
  python scripts/run_eval.py --date 2026-08-08 --output data/
  python scripts/run_eval.py --date 2026-08-08 --output data/ --demo   # 不调 API, 用 seeded 数据
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import date as date_cls
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CONFIG_DIR = ROOT / "config"

# ----------------------------------------------------------------------------
# Citation extraction
# ----------------------------------------------------------------------------
# Matches Chinese statute citations like: 《民法典》第584条 / 《刑法》第20条第2款
CITATION_RE = re.compile(r"《([^》]+)》\s*第\s*([0-9零一二三四五六七八九十百千]+)\s*条(?:\s*第\s*([0-9零一二三四五六七八九十百千]+)\s*款)?")

# Statuses that count as hallucination
HALLUCINATION_STATUSES = {"✗MA", "✗NF", "✗F"}


def extract_citations(text: str) -> list[str]:
    """Return a list of normalized citation strings found in `text`."""
    out = []
    for m in CITATION_RE.finditer(text or ""):
        law, article, clause = m.group(1), m.group(2), m.group(3)
        cite = f"《{law}》第{article}条"
        if clause:
            cite += f"第{clause}款"
        out.append(cite)
    return out


# ----------------------------------------------------------------------------
# Model API (OpenAI-compatible)
# ----------------------------------------------------------------------------
def call_model(model_cfg: dict, prompt: str, api_key: str, timeout: int = 60) -> str:
    """Call an OpenAI-compatible chat endpoint and return the assistant text."""
    if not api_key:
        raise RuntimeError(
            f"No API key for {model_cfg['id']} (env {model_cfg['api_key_env']}). "
            "Set it or run with --demo."
        )
    try:
        import requests
    except ImportError:  # pragma: no cover
        raise RuntimeError("Missing dependency: requests.  Install with `pip install requests`.")
    payload = {
        "model": model_cfg["model"],
        "messages": [
            {"role": "system", "content": "你是一名严谨的中国法律助手。回答时如需援引法条，必须给出准确的法条名称与条号，例如《民法典》第584条。不要编造不存在的法条。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.0,
        "max_tokens": 1024,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    resp = requests.post(model_cfg["api_base"], json=payload, headers=headers, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


# ----------------------------------------------------------------------------
# Verification
# ----------------------------------------------------------------------------
def _try_import_bench_verifier():
    """Best-effort import of the bench verification engine. Returns callable or None."""
    try:
        # If bench is installed as a package or present as submodule
        import importlib

        mod = importlib.import_module("legal_hallucination_bench.verify")
        return mod.verify_citation
    except Exception:
        # Also try submodule path
        bench_path = ROOT / "legal-hallucination-bench"
        if bench_path.exists():
            sys.path.insert(0, str(bench_path))
            try:
                import importlib

                mod = importlib.import_module("legal_hallucination_bench.verify")
                return mod.verify_citation
            except Exception:
                return None
    return None


def verify_local(question: dict, answer: str) -> dict:
    """
    Local fallback verifier (DEMO ONLY).

    Heuristic: for a verifiable question with an expected_citation, check whether
    the answer contains a correctly formatted citation matching the expected one.
    This is intentionally simple and NOT authoritative — production delegates to
    the bench engine which checks against the authoritative statute knowledge base.
    """
    citations = extract_citations(answer)
    expected = question.get("expected_citation", "")
    norm_expected = expected.replace(" ", "")

    if not citations:
        return {"status": "·", "detail": "未识别到法条引注", "citations": []}

    # Check if any extracted citation matches the expected one (ignoring spaces)
    matched = any(c.replace(" ", "") == norm_expected for c in citations)
    if matched:
        return {"status": "✓", "detail": f"命中预期引注 {expected}", "citations": citations}
    # A citation exists but does not match the expected verifiable citation
    return {
        "status": "✗MA",
        "detail": f"引注与预期不符 (期望 {expected}, 实际 {citations[0]})",
        "citations": citations,
    }


def verify_answer(verifier, question: dict, answer: str) -> dict:
    if verifier is not None:
        try:
            return verifier(question, answer)
        except Exception as e:  # pragma: no cover - fall back gracefully
            print(f"  [warn] bench verifier failed ({e}); using local fallback", flush=True)
    return verify_local(question, answer)


# ----------------------------------------------------------------------------
# Evaluation loop
# ----------------------------------------------------------------------------
def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def run_evaluation(eval_date: str, output_root: Path, demo: bool = False):
    models = load_json(CONFIG_DIR / "models.json")["models"]
    questions = load_json(CONFIG_DIR / "questions.json")["questions"]

    verifier = None if demo else _try_import_bench_verifier()
    if not demo and verifier is None:
        print("[info] bench verifier not found; using local fallback verifier.", flush=True)

    day_dir = output_root / "answers" / eval_date
    day_dir.mkdir(parents=True, exist_ok=True)

    answers_path = day_dir / "answers.jsonl"
    verifications_path = day_dir / "verifications.jsonl"

    model_results = {}  # model_id -> list of verification records
    answer_records = []

    # ---- demo mode: reuse seeded verifications (no API calls) -------------
    if demo:
        seeded = day_dir / "verifications.jsonl"
        if not seeded.exists():
            sys.exit(
                f"Demo mode needs seeded data at {seeded}.\n"
                "Run `python scripts/seed_demo.py` first (it writes demo answers/verifications).\n"
                "Then re-run with --demo to recompute the leaderboard from seeded results."
            )
        print(f"[demo] reusing seeded verifications from {seeded}", flush=True)
        with open(seeded, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                model_results.setdefault(r["model"], []).append(r)
        # write answers.jsonl placeholder only if missing (keep seed if present)
        if not answers_path.exists():
            with open(answers_path, "w", encoding="utf-8") as f:
                f.write("")  # demo: answers not regenerated
        _finalize(output_root, model_results, eval_date, verifications_path)
        return 

    for model in models:
        if not model.get("enabled", True):
            continue
        print(f"[eval] model={model['id']}", flush=True)
        verifs = []
        for q in questions:
            record = {
                "qid": q["qid"],
                "domain": q.get("domain", "未分类"),
                "question": q["prompt"],
                "model": model["id"],
            }
            api_key = os.environ.get(model["api_key_env"], "")
            try:
                answer = call_model(model, q["prompt"], api_key)
            except Exception as e:
                print(f"  [error] {model['id']} q{q['qid']}: {e}", flush=True)
                answer = ""
            time.sleep(0.5)  # polite rate limiting

            v = verify_answer(verifier, q, answer)
            record.update({"status": v["status"], "detail": v["detail"], "citations": v["citations"]})
            answer_records.append({"model": model["id"], "qid": q["qid"], "answer": answer})
            verifs.append(record)
        model_results[model["id"]] = verifs

    # Write answers.jsonl
    with open(answers_path, "w", encoding="utf-8") as f:
        for r in answer_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Write verifications, leaderboard, and history
    _finalize(output_root, model_results, eval_date, verifications_path)
    return build_leaderboard(model_results)


def _finalize(output_root: Path, model_results: dict, eval_date: str, verifications_path: Path):
    """Write verifications.jsonl, leaderboard.json, and append to history."""
    day_dir = verifications_path.parent
    models = load_json(CONFIG_DIR / "models.json")["models"]
    questions = load_json(CONFIG_DIR / "questions.json")["questions"]

    all_verifs = []
    for verifs in model_results.values():
        all_verifs.extend(verifs)
    with open(verifications_path, "w", encoding="utf-8") as f:
        for r in all_verifs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    leaderboard = build_leaderboard(model_results)
    domain_hvi = build_domain_hvi(model_results)
    with open(day_dir / "leaderboard.json", "w", encoding="utf-8") as f:
        json.dump({"date": eval_date, "leaderboard": leaderboard, "domain_hvi": domain_hvi},
                  f, ensure_ascii=False, indent=2)

    history_path = output_root / "leaderboard_history.json"
    history = load_json(history_path) if history_path.exists() else {
        "updated_at": eval_date, "models": [], "domains": [], "history": []}
    history["history"] = [h for h in history["history"] if h["date"] != eval_date]
    history["history"].append({"date": eval_date, "leaderboard": leaderboard, "domain_hvi": domain_hvi})
    history["history"].sort(key=lambda h: h["date"])
    history["updated_at"] = eval_date
    history["models"] = [m["id"] for m in models if m.get("enabled", True)]
    history["domains"] = sorted({q.get("domain", "未分类") for q in questions})
    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    print(f"[done] wrote {verifications_path}, {day_dir / 'leaderboard.json'}")
    print(f"[done] updated {history_path}")


def build_leaderboard(model_results: dict) -> list[dict]:
    rows = []
    for model_id, verifs in model_results.items():
        denom = [v for v in verifs if v["status"] in {"✓", "✗MA", "✗NF", "✗F"}]
        total = len(denom)
        hallucinated = sum(1 for v in denom if v["status"] in HALLUCINATION_STATUSES)
        correct = sum(1 for v in denom if v["status"] == "✓")
        hvi = round(hallucinated / total, 4) if total else 0.0
        crfi = round(correct / total, 4) if total else 0.0
        rows.append({
            "model": model_id,
            "hvi": hvi,
            "citations": total,
            "crfi": crfi,
            "temporal": 0.0,  # populated by bench verifier in production
            "answered": len(verifs),
        })
    rows.sort(key=lambda r: (r["hvi"], -r["citations"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


def build_domain_hvi(model_results: dict) -> dict:
    out = {}
    for model_id, verifs in model_results.items():
        by_domain: dict[str, list] = {}
        for v in verifs:
            by_domain.setdefault(v["domain"], []).append(v)
        out[model_id] = {}
        for dom, vs in by_domain.items():
            denom = [v for v in vs if v["status"] in {"✓", "✗MA", "✗NF", "✗F"}]
            total = len(denom)
            hall = sum(1 for v in denom if v["status"] in HALLUCINATION_STATUSES)
            out[model_id][dom] = round(hall / total, 4) if total else 0.0
    return out


def main():
    ap = argparse.ArgumentParser(description="Run Legal AI Watch weekly evaluation")
    ap.add_argument("--date", default=date_cls.today().isoformat(), help="evaluation date YYYY-MM-DD")
    ap.add_argument("--output", default=str(ROOT / "data"), help="data output root")
    ap.add_argument("--demo", action="store_true", help="demo mode: no API calls (seeded verifications required)")
    args = ap.parse_args()

    output_root = Path(args.output)
    output_root.mkdir(parents=True, exist_ok=True)
    run_evaluation(args.date, output_root, demo=args.demo)


if __name__ == "__main__":
    main()
