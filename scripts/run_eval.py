#!/usr/bin/env python3
"""
run_eval.py — Legal AI Watch 主评测脚本

流程: 对 config/models.json 中的每个启用模型, 调用其 OpenAI 兼容聊天接口,
     抽取回答中的法条引注, 使用**本地确定性核验引擎** (scripts/verifier.py,
     官方方法学, 见 docs/METHODOLOGY.md §7) 逐条判定, 产出:
        data/answers/YYYY-MM-DD/answers.jsonl
        data/answers/YYYY-MM-DD/verifications.jsonl
        data/answers/YYYY-MM-DD/leaderboard.json
     并将本轮排行榜追加写入 data/leaderboard_history.json.

设计原则:
  - 核验质量=产品本身: 采用确定性、离线、可审计的 verifier, 不再依赖沉默失败的
    "bench 兜底". 引注先归一化到 canonical 法条 provision (跨版本/跨法等价), 再比对.
  - 指标诚实:
      * HVI  = 错引 / (正确 + 错引)             —— 一旦引注, 多大概率错 (纯幻觉率)
      * CRFI = 正确 / (正确 + 错引)             —— 引注正确率
      * Coverage = (正确+错引) / (正确+错引+未引注) —— 引注纪律/参与度
      * Integrity = 正确 / (正确+错引+未引注)   —— 综合正确率, 逃避引注被计为不正确
      * Temporal = 时序幻觉 / (正确+错引+时序幻觉) —— 引用已废止旧法的比例
      * api_errors                              —— 接口调用失败次数 (基础设施问题, 单列, 不混入模型行为)
    "未引注"不再被悄悄豁免: 它拉低 Coverage/Integrity, 在榜单上可见.
  - 抑制非确定性: 每题每模型取样 N 次 (--samples, 默认 3), 矩阵取多数判定,
    HVI/CRFI/分域 HVI/时序 跨全部取样汇总, 摊薄方差. cell 标注 "k/n 取样" 透明化.
  - 健壮性: 429/5xx/网络抖动可重试并尊重 Retry-After; 401/403/404 快速失败;
    接口彻底失败记为 ✗ERR (区别于"未引注"), 不在 HVI 中冒充模型行为.

Usage:
  python scripts/run_eval.py --date 2026-08-14 --output data/
  python scripts/run_eval.py --date 2026-08-14 --output data/ --locale en
  python scripts/run_eval.py --demo   # 不调 API, 用 seeded 数据重算
  python scripts/run_eval.py --limit 5   # 烟雾测试: 仅前5题, 真·API, 不碰公开看板
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date as date_cls
from pathlib import Path

from verifier import (
    Equivalence,
    HALLUCINATION_STATUSES,
    extract_citations,
    verify as verify_fn,
)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CONFIG_DIR = ROOT / "config"
PROMPTS_PATH = CONFIG_DIR / "prompts.json"
EQUIV_PATH = CONFIG_DIR / "statute_equivalence.json"


class ModelCallError(RuntimeError):
    """Raised when a model API call fails after all retries (or fails fast)."""


# ----------------------------------------------------------------------------
# Model API (OpenAI-compatible) with principled retry / backoff
# ----------------------------------------------------------------------------
def _load_prompts(locale: str) -> str:
    key = "system_prompt_en" if locale == "en" else "system_prompt_zh"
    fallback = (
        "You are a rigorous PRC legal assistant. Cite accurate law name and article."
        if locale == "en" else
        "你是一名严谨的中国法律助手。回答时如需援引法条，必须给出准确的法条名称与条号，"
        "例如《民法典》第584条。不要编造不存在的法条；若不确定，应明确说明而非猜测。"
    )
    if not PROMPTS_PATH.exists():
        return fallback
    try:
        data = json.loads(PROMPTS_PATH.read_text(encoding="utf-8"))
        return data.get(key, fallback)
    except Exception:
        return fallback


def call_model(model_cfg: dict, prompt: str, api_key: str, system_prompt: str,
               timeout: int = 120, max_retries: int = 5, backoff: float = 2.0,
               min_interval: float = 0.5) -> str:
    """Call an OpenAI-compatible chat endpoint and return the assistant text.

    Retry policy (principled, not fail-fast-for-everything):
      * 429 / 5xx (HTTPError with retryable status) → retry with exponential
        backoff, honoring the server's `Retry-After` header when present.
      * network errors (ReadTimeout / ConnectionError) → retry.
      * non-JSON response body → retry (transient gateway glitch).
      * 401 / 403 / 404 (auth or config error) → fail fast, do NOT retry.
    Raises ModelCallError on final failure so the caller records an explicit
    ✗ERR verdict rather than silently turning the empty answer into "未作答".
    """
    if not api_key:
        raise ModelCallError(
            f"No API key for {model_cfg['id']} (env {model_cfg['api_key_env']}). "
            "Set it or run with --demo."
        )
    try:
        import requests
        from requests.exceptions import ReadTimeout, ConnectionError as ConnError
    except ImportError:
        raise ModelCallError("Missing dependency: requests. Install with `pip install requests`.")

    max_tokens = int(model_cfg.get("max_tokens", 2048))
    payload = {
        "model": model_cfg["model"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.0,
        "max_tokens": max_tokens,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    last_err: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(model_cfg["api_base"], json=payload, headers=headers, timeout=timeout)
            status = resp.status_code
            # ---- fail-fast: auth / config errors ----
            if status in (401, 403, 404):
                raise ModelCallError(f"{model_cfg['id']} HTTP {status} (auth/config error, not retried)")
            # ---- retryable: rate limit / server errors ----
            if status >= 500 or status == 429:
                retry_after = resp.headers.get("Retry-After")
                wait = float(retry_after) if (retry_after and retry_after.isdigit()) else backoff * (2 ** (attempt - 1))
                if attempt < max_retries:
                    print(f"  [warn] {model_cfg['id']} HTTP {status}; retry in {wait:.0f}s "
                          f"(attempt {attempt}/{max_retries})", flush=True)
                    time.sleep(wait)
                    continue
                raise ModelCallError(f"{model_cfg['id']} HTTP {status} after {max_retries} retries")
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
        except ModelCallError:
            raise
        except (ReadTimeout, ConnError) as e:  # transient network — retry
            last_err = e
            if attempt < max_retries:
                wait = backoff * (2 ** (attempt - 1))
                print(f"  [warn] {model_cfg['id']} {type(e).__name__}; retry in {wait:.0f}s "
                      f"(attempt {attempt}/{max_retries})", flush=True)
                time.sleep(wait)
                continue
            raise ModelCallError(f"{model_cfg['id']} network error after {max_retries} retries: {e}")
        except ValueError:  # JSON decode error — transient gateway glitch, retry
            last_err = ValueError("non-JSON response")
            if attempt < max_retries:
                wait = backoff * (2 ** (attempt - 1))
                print(f"  [warn] {model_cfg['id']} non-JSON response; retry in {wait:.0f}s "
                      f"(attempt {attempt}/{max_retries})", flush=True)
                time.sleep(wait)
                continue
            raise ModelCallError(f"{model_cfg['id']} non-JSON response after {max_retries} retries")
        except Exception as e:  # any other unexpected — fail fast
            raise ModelCallError(f"{model_cfg['id']} unexpected error: {e}")

    raise last_err if last_err else ModelCallError("unknown model-call error")


# ----------------------------------------------------------------------------
# Verification dispatch
# ----------------------------------------------------------------------------
def verify_answer(question: dict, answer: str, eq: Equivalence) -> dict:
    """Verify a single answer. The local deterministic verifier IS the official
    methodology (docs/METHODOLOGY.md §7)."""
    return verify_fn(question, answer, eq)


# ----------------------------------------------------------------------------
# Aggregation (N samples -> one per-question record)
# ----------------------------------------------------------------------------
# Tie-break priority for the *displayed* per-question verdict. Conservative for a
# hallucination-watch board: a hallucination verdict outranks a correct one, and
# an explicit API error (✗ERR) is surfaced when no hallucination is present.
_STATUS_PRIORITY = ["✗MA", "✗NF", "✗T", "✗ERR", "✓", "·", "?"]


def aggregate_samples(model_id: str, question: dict, samples_results, n_samples: int) -> dict:
    """Collapse N per-sample verifications into one aggregated per-question record.

    `samples_results` is a list of (answer_text, verification_dict). We compute:
      * `counts`        — how many samples fell into each status,
      * `majority`      — most frequent status (tie-broken by _STATUS_PRIORITY),
      * `_correct/_wrong/_nocite/_temporal/_api_err/_unverif` — pooled tallies used
        by build_leaderboard / build_domain_hvi (HVI averaged over all samples),
      * `detail`        — representative detail annotated with the sample split.
    """
    statuses = [v["status"] for _, v in samples_results]
    counts: dict[str, int] = {}
    for s in statuses:
        counts[s] = counts.get(s, 0) + 1

    max_c = max(counts.values())
    tied = [s for s in counts if counts[s] == max_c]
    majority = sorted(tied, key=lambda s: _STATUS_PRIORITY.index(s)
                      if s in _STATUS_PRIORITY else 99)[0]

    correct = counts.get("✓", 0)
    wrong = sum(counts.get(s, 0) for s in HALLUCINATION_STATUSES)
    nocite = counts.get("·", 0)
    temporal = counts.get("✗T", 0)
    api_err = counts.get("✗ERR", 0)
    unverif = counts.get("?", 0)

    rep_answer = next((a for a, v in samples_results if v["status"] == majority), samples_results[0][0])
    rep_v = next((v for a, v in samples_results if v["status"] == majority), samples_results[0][1])
    rep_citations = rep_v.get("citations", [])

    if majority == "✓":
        detail = f"{rep_v['detail']}（{correct}/{n_samples} 取样正确）"
    elif majority in HALLUCINATION_STATUSES:
        detail = f"{rep_v['detail']}（{counts.get(majority, 0)}/{n_samples} 取样错引）"
    elif majority == "✗ERR":
        detail = f"接口调用失败（{api_err}/{n_samples} 取样报错）"
    elif majority == "·":
        detail = f"未识别到法条引注（{nocite}/{n_samples} 取样无引注）"
    else:
        detail = rep_v.get("detail", "无法判定")

    return {
        "qid": question["qid"],
        "domain": question.get("domain", "未分类"),
        "question": question["prompt"],
        "model": model_id,
        "status": majority,
        "detail": detail,
        "citations": rep_citations,
        "_correct": correct,
        "_wrong": wrong,
        "_nocite": nocite,
        "_temporal": temporal,
        "_api_err": api_err,
        "_unverif": unverif,
        "_counts": counts,
    }


def _augment_single_for_leaderboard(rec: dict):
    """Backfill internal tally fields for a single-sample (demo) record."""
    st = rec.get("status", "?")
    rec["_correct"] = 1 if st == "✓" else 0
    rec["_wrong"] = 1 if st in HALLUCINATION_STATUSES else 0
    rec["_nocite"] = 1 if st == "·" else 0
    rec["_temporal"] = 1 if st == "✗T" else 0
    rec["_api_err"] = 1 if st == "✗ERR" else 0
    rec["_unverif"] = 1 if st == "?" else 0
    rec["_counts"] = {st: 1}


# ----------------------------------------------------------------------------
# Evaluation loop
# ----------------------------------------------------------------------------
def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def run_evaluation(eval_date: str, output_root: Path, demo: bool = False,
                   samples: int = 3, locale: str = "zh", limit: int = 0):
    models = load_json(CONFIG_DIR / "models.json")["models"]
    questions = load_json(CONFIG_DIR / "questions.json")["questions"]
    eq = Equivalence.load(EQUIV_PATH)
    system_prompt = _load_prompts(locale)

    # smoke 模式: 只评测前 `limit` 题, 结果写到 data/smoke/, 且**不更新公开排行榜
    # 历史**。用于密钥换更后做一次"真·API 端到端"的极便宜验证, 既不花全量调用的钱,
    # 也不会污染公开看板。full 模式 (limit=0) 行为与以往完全一致。
    smoke = (not demo) and (limit and limit > 0)
    if smoke:
        questions = questions[:limit]

    day_dir = (output_root / "smoke" / eval_date) if smoke else (output_root / "answers" / eval_date)
    day_dir.mkdir(parents=True, exist_ok=True)
    if smoke:
        print(f"[smoke] limit={limit}: 仅评测前 {len(questions)} 题; 结果写入 "
              f"data/smoke/{eval_date}/, 不更新公开排行榜历史。", flush=True)

    answers_path = day_dir / "answers.jsonl"
    verifications_path = day_dir / "verifications.jsonl"

    model_results = {}
    answer_records = []

    # ---- demo mode: reuse seeded verifications (no API calls) -------------
    if demo:
        seeded = day_dir / "verifications.jsonl"
        if not seeded.exists():
            sys.exit(
                f"Demo mode needs seeded data at {seeded}.\n"
                "Run `python scripts/seed_demo.py` first, then re-run with --demo."
            )
        print(f"[demo] reusing seeded verifications from {seeded}", flush=True)
        with open(seeded, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                _augment_single_for_leaderboard(r)
                model_results.setdefault(r["model"], []).append(r)
        if not answers_path.exists():
            with open(answers_path, "w", encoding="utf-8") as f:
                f.write("")
        _finalize(output_root, model_results, eval_date, verifications_path)
        return

    print(f"[info] verifier: local deterministic engine (official methodology, "
          f"{len(eq.repealed_laws)} repealed laws tracked, "
          f"{len(eq._map)} equivalent provision mappings)", flush=True)

    for model in models:
        if not model.get("enabled", True):
            continue
        api_key_env = model["api_key_env"]
        api_key = os.environ.get(api_key_env, "")
        if not api_key:
            # 密钥缺失：直接跳过该模型，避免 90 行空 ✗ERR 污染公开榜单。
            # 配置好对应 CI Secret / 本地环境变量后，下轮会自动纳入评测。
            print(f"[skip] model={model['id']}: 环境变量 {api_key_env} 为空/未设置，跳过"
                  f"（不调用 API、不写入空结果）。请配置该密钥后重跑。", flush=True)
            continue
        min_interval = float(model.get("min_interval_seconds", 0.5))
        print(f"[eval] model={model['id']} (sampling x{samples}, locale={locale})", flush=True)
        verifs = []
        # 认证类错误（401/403/404/缺密钥）整轮 fail-fast：密钥不会在单次运行中途恢复，
        # 没必要为每个问题重复烧 90 次无效调用；首题命中即跳过剩余题，错误文本落盘。
        auth_failed = False
        auth_err_msg = ""
        for q in questions:
            if auth_failed:
                # 复用同一认证错误文本，标注整题 ✗ERR，避免重复调用 API
                verifs.append({
                    "qid": q["qid"], "domain": q.get("domain", "未分类"),
                    "question": q["prompt"], "model": model["id"],
                    "status": "✗ERR", "detail": auth_err_msg, "citations": [],
                    "_api_err": samples, "_counts": {"✗ERR": samples},
                })
                continue
            prompt = q.get("prompt_en") if (locale == "en" and q.get("prompt_en")) else q["prompt"]
            samples_results = []
            for s_idx in range(samples):
                answer = ""
                try:
                    answer = call_model(model, prompt, api_key, system_prompt)
                    v = verify_answer(q, answer, eq)
                except ModelCallError as e:
                    print(f"  [error] {model['id']} q{q['qid']} sample{s_idx+1}: {e}", flush=True)
                    msg = str(e)
                    if "auth/config" in msg or "No API key" in msg:
                        auth_failed = True
                        auth_err_msg = msg
                    v = {"status": "✗ERR", "detail": msg, "citations": []}
                time.sleep(min_interval)
                samples_results.append((answer, v))
            agg = aggregate_samples(model["id"], q, samples_results, samples)
            answer_records.append({
                "model": model["id"],
                "qid": q["qid"],
                "answer": next((a for a, v in samples_results if v["status"] != "✗ERR"), ""),
                "answers": [a for a, _ in samples_results],
                "n_samples": samples,
                "counts": agg["_counts"],
                # 若本 cell 有取样报错，把错误文本一并落盘，便于在公开看板审计中直接定位原因
                "error": next((v.get("detail") for a, v in samples_results if v["status"] == "✗ERR"), None),
            })
            verifs.append(agg)
        model_results[model["id"]] = verifs

    with open(answers_path, "w", encoding="utf-8") as f:
        for r in answer_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    _finalize(output_root, model_results, eval_date, verifications_path,
              write_history=not smoke)
    return build_leaderboard(model_results)


def _finalize(output_root: Path, model_results: dict, eval_date: str, verifications_path: Path,
              write_history: bool = True):
    day_dir = verifications_path.parent
    models = load_json(CONFIG_DIR / "models.json")["models"]
    questions = load_json(CONFIG_DIR / "questions.json")["questions"]

    all_verifs = []
    for verifs in model_results.values():
        all_verifs.extend(verifs)
    with open(verifications_path, "w", encoding="utf-8") as f:
        for r in all_verifs:
            clean = {k: v for k, v in r.items() if not k.startswith("_")}
            f.write(json.dumps(clean, ensure_ascii=False) + "\n")

    leaderboard = build_leaderboard(model_results)
    domain_hvi = build_domain_hvi(model_results)
    with open(day_dir / "leaderboard.json", "w", encoding="utf-8") as f:
        json.dump({"date": eval_date, "leaderboard": leaderboard, "domain_hvi": domain_hvi},
                  f, ensure_ascii=False, indent=2)

    print(f"[done] wrote {verifications_path}, {day_dir / 'leaderboard.json'}")

    if not write_history:
        # smoke 模式: 不污染公开排行榜历史, 看板读不到本次结果。
        print(f"[smoke] 跳过 {output_root / 'leaderboard_history.json'} 写入（smoke 模式不更新公开看板）")
        return

    history_path = output_root / "leaderboard_history.json"
    history = load_json(history_path) if history_path.exists() else {
        "updated_at": date_cls.today().isoformat(), "models": [], "domains": [], "history": []}
    # de-dup: drop any existing entry for the same date
    history["history"] = [h for h in history["history"] if h.get("date") != eval_date]
    history["history"].append({
        "date": eval_date,
        "leaderboard": leaderboard,
        "domain_hvi": domain_hvi,
    })
    history["updated_at"] = eval_date
    history["models"] = list(dict.fromkeys(
        [r["model"] for r in leaderboard] + list(history.get("models", []))))
    history["domains"] = sorted({q.get("domain", "未分类") for q in questions})
    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    print(f"[done] updated {history_path}")


def build_leaderboard(model_results: dict) -> list[dict]:
    rows = []
    for model_id, verifs in model_results.items():
        correct = sum(v.get("_correct", 0) for v in verifs)
        wrong = sum(v.get("_wrong", 0) for v in verifs)
        nocite = sum(v.get("_nocite", 0) for v in verifs)
        temporal = sum(v.get("_temporal", 0) for v in verifs)
        api_err = sum(v.get("_api_err", 0) for v in verifs)
        total_cited = correct + wrong
        total_engaged = correct + wrong + nocite

        cited_questions = sum(1 for v in verifs
                              if v["status"] in {"✓", "✗MA", "✗T"})

        if total_cited == 0:
            # Model cited nothing verifiable across all samples → "未作答".
            hvi = crfi = coverage = integrity = temporal_score = None
            rank = None
        else:
            hvi = round(wrong / total_cited, 4)
            crfi = round(correct / total_cited, 4)
            coverage = round((correct + wrong) / total_engaged, 4) if total_engaged else None
            integrity = round(correct / total_engaged, 4) if total_engaged else None
            temporal_score = round(temporal / total_cited, 4) if total_cited else None
            rank = 0

        rows.append({
            "model": model_id,
            "hvi": hvi,
            "crfi": crfi,
            "coverage": coverage,
            "integrity": integrity,
            "temporal": temporal_score,
            "citations": cited_questions,
            "api_errors": api_err,
            "answered": len(verifs),
            "rank": rank,
        })
    # Answered models first (by HVI asc, then more citations, then fewer api errors)
    rows.sort(key=lambda r: (1 if r["hvi"] is None else 0,
                             r["hvi"] if r["hvi"] is not None else 0.0,
                             -r["citations"],
                             r["api_errors"]))
    answered = [r for r in rows if r["hvi"] is not None]
    for i, r in enumerate(answered, 1):
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
            correct = sum(v.get("_correct", 0) for v in vs)
            wrong = sum(v.get("_wrong", 0) for v in vs)
            total = correct + wrong
            out[model_id][dom] = round(wrong / total, 4) if total else None
    return out


def main():
    ap = argparse.ArgumentParser(description="Run Legal AI Watch weekly evaluation")
    ap.add_argument("--date", default=date_cls.today().isoformat(), help="evaluation date YYYY-MM-DD")
    ap.add_argument("--output", default=str(ROOT / "data"), help="data output root")
    ap.add_argument("--demo", action="store_true", help="demo mode: no API calls (seeded verifications required)")
    ap.add_argument("--samples", type=int, default=3, help="samples per (model, question) (default 3)")
    ap.add_argument("--locale", choices=["zh", "en"], default="zh", help="question/prompt locale")
    ap.add_argument("--limit", type=int, default=0,
                    help="smoke test: evaluate only the first N questions "
                         "(writes to data/smoke, skips public leaderboard history)")
    args = ap.parse_args()

    output_root = Path(args.output)
    output_root.mkdir(parents=True, exist_ok=True)
    run_evaluation(args.date, output_root, demo=args.demo, samples=args.samples,
                   locale=args.locale, limit=args.limit)


if __name__ == "__main__":
    main()
