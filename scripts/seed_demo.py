#!/usr/bin/env python3
"""
seed_demo.py — 生成 12 周演示数据 (无需任何 API Key)

用途:
  - 本地预览 Dashboard 时, 让趋势图 / 排行榜 / 矩阵都有真实感数据。
  - CI 之外, 任何人 clone 后都能 `python scripts/seed_demo.py && python
    scripts/generate_dashboard.py` 看到完整页面。

注意: 这是**演示数据**, 不代表任何模型的真实表现。正式数据由 weekly-eval.yml
调用 run_eval.py (命中真实模型 API) 产生并覆盖。

产出:
  data/leaderboard_history.json
  data/model_metadata.json
  data/answers/<最新日期>/{answers,verifications}.jsonl
"""
from __future__ import annotations

import json
import random
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CONFIG = ROOT / "config"

# ---- demo configuration -----------------------------------------------------
MODELS = ["DeepSeek-R1", "Qwen-Max", "GLM-4"]  # 与生产 config/models.json 的启用集保持一致（Kimi 已退出评测池）
# base HVI at week 0 and week -11 (trend), plus per-domain offset
MODEL_PROFILE = {
    "DeepSeek-R1": {"start": 0.58, "end": 0.50, "temporal": 0.12},
    "Qwen-Max":    {"start": 0.61, "end": 0.55, "temporal": 0.15},
    "GLM-4":       {"start": 0.66, "end": 0.62, "temporal": 0.18},
}
# domain difficulty multiplier applied to a model's base HVI
DOMAIN_BIAS = {"民法": 0.95, "刑法": 0.55, "税法": 1.35, "专利": 0.80,
               "公司法": 1.10, "数据合规": 1.20, "竞争法": 0.90}
CITATIONS_RANGE = (38, 50)

METADATA = {
    "DeepSeek-R1": {"vendor": "DeepSeek", "version": "R1 (2501)", "params": "671B MoE", "context": "64K", "release": "2025-01"},
    "Qwen-Max":    {"vendor": "Alibaba", "version": "qwen-max", "params": "—", "context": "32K", "release": "2024-09"},
    "GLM-4":       {"vendor": "Zhipu AI", "version": "glm-4", "params": "—", "context": "128K", "release": "2024-06"},
}

SEED = 20260808
WEEKS = 12
END_DATE = date(2026, 8, 8)


def build_questions():
    q = json.loads((CONFIG / "questions.json").read_text(encoding="utf-8"))
    return q["questions"]


def gen_history():
    random.seed(SEED)
    dates = [(END_DATE - timedelta(weeks=WEEKS - 1 - i)) for i in range(WEEKS)]
    history = []
    domains = sorted(DOMAIN_BIAS.keys())
    for wi, d in enumerate(dates):
        frac = wi / (WEEKS - 1)  # 0..1 progress
        leaderboard = []
        domain_hvi = {}
        for m in MODELS:
            prof = MODEL_PROFILE[m]
            base = prof["start"] + (prof["end"] - prof["start"]) * frac
            hvi = max(0.02, min(0.95, base + random.uniform(-0.03, 0.03)))
            citations = random.randint(*CITATIONS_RANGE)
            crfi = max(0.0, 1 - hvi - random.uniform(0.0, 0.04))
            temporal = max(0.0, prof["temporal"] + random.uniform(-0.04, 0.04))
            leaderboard.append({
                "model": m, "hvi": round(hvi, 4), "citations": citations,
                "crfi": round(crfi, 4), "temporal": round(temporal, 4), "answered": citations,
            })
            domain_hvi[m] = {}
            for dom in domains:
                dh = max(0.02, min(0.97, hvi * DOMAIN_BIAS[dom] + random.uniform(-0.04, 0.04)))
                domain_hvi[m][dom] = round(dh, 4)
        leaderboard.sort(key=lambda r: (r["hvi"], -r["citations"]))
        for i, r in enumerate(leaderboard, 1):
            r["rank"] = i
        history.append({"date": d.isoformat(), "leaderboard": leaderboard, "domain_hvi": domain_hvi})
    return {"updated_at": END_DATE.isoformat(), "models": MODELS, "domains": domains, "history": history}


def gen_latest_answers(history, questions):
    random.seed(SEED + 1)
    latest = history["history"][-1]
    d = latest["date"]
    day_dir = DATA / "answers" / d
    day_dir.mkdir(parents=True, exist_ok=True)
    model_hvi = {r["model"]: r["hvi"] for r in latest["leaderboard"]}

    answers = []
    verifications = []
    for q in questions:
        dom = q.get("domain", "未分类")
        expected = q.get("expected_citation", "")
        for m in MODELS:
            dh = latest["domain_hvi"][m].get(dom, model_hvi.get(m, 0.5))
            is_hall = random.random() < dh
            if not is_hall:
                status = "✓"
                detail = f"命中预期引注 {expected}"
                answer = (f"根据{expect_dom_lead(dom)}{expected}的规定，"
                          f"{q['prompt'][:18]}……该条文内容如下，适用结论成立。")
            else:
                # pick a hallucination subtype — only statuses the verifier
                # actually emits (✗MA made-up article / ✗T temporal-version).
                sub = random.choice(["✗MA", "✗T"])
                if sub == "✗MA":
                    wrong = fake_citation(expected)
                    status = "✗MA"
                    detail = f"编造/不存在的引注 {wrong}"
                    answer = f"根据{wrong}的规定，{q['prompt'][:18]}……"
                else:  # ✗T temporal / version hallucination
                    status = "✗T"
                    detail = f"援引已废止/旧版本法条（期望现行法 {expected}）"
                    answer = f"根据{expected}（已废止旧版）的规定，{q['prompt'][:18]}……"
            answers.append({"model": m, "qid": q["qid"], "answer": answer})
            verifications.append({
                "qid": q["qid"], "domain": dom, "question": q["prompt"],
                "model": m, "status": status, "detail": detail,
                "citations": [expected] if status == "✓" else [fake_citation(expected) if status == "✗MA" else expected],
            })
    (day_dir / "answers.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in answers) + "\n", encoding="utf-8")
    (day_dir / "verifications.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in verifications) + "\n", encoding="utf-8")
    return d


def expect_dom_lead(dom):
    return {"民法": "《民法典》", "刑法": "《刑法》", "税法": "相关税收法规", "专利": "《专利法》", "公司法": "《公司法》"}.get(dom, "")


def fake_citation(expected):
    # produce a plausible-but-wrong citation by bumping the article number
    import re
    m = re.search(r"第\s*([0-9]+)\s*条", expected)
    if m:
        num = int(m.group(1))
        return expected.replace(f"第{num}条", f"第{num+7}条")
    return "《虚构法》第999条"


def main():
    questions = build_questions()
    history = gen_history()
    (DATA / "leaderboard_history.json").write_text(
        json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    (DATA / "model_metadata.json").write_text(
        json.dumps(METADATA, ensure_ascii=False, indent=2), encoding="utf-8")
    d = gen_latest_answers(history, questions)
    print(f"[seed] generated {WEEKS} weeks of demo history (ending {d})")
    print(f"[seed] wrote data/leaderboard_history.json, data/model_metadata.json")
    print(f"[seed] wrote data/answers/{d}/{{answers,verifications}}.jsonl")
    print("[seed] next: python scripts/generate_dashboard.py")


if __name__ == "__main__":
    main()
