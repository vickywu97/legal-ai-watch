#!/usr/bin/env python3
"""
generate_dashboard.py — 由 data/ 生成静态 Dashboard (dashboard/index.html)

读取:
  data/leaderboard_history.json   (排行榜历史, 趋势图 & 主表 & 跨期对比)
  data/model_metadata.json        (模型厂商/版本等元数据, 退回 config/)
  data/answers/<最新日期>/verifications.jsonl  (逐题诊断矩阵)
  data/answers/<最新日期>/answers.jsonl        (逐题模型原话, 用于下钻)

产出:
  dashboard/index.html   内联数据 + 引入 style.css / dashboard.js
  dashboard/status.json  新鲜度元数据 (generated_at / data_date / 模型数 / 题数)
  dashboard/style.css
  dashboard/dashboard.js

数据以内联 JSON (window.__WATCH__) 形式写入 HTML, 避免本地预览的 fetch/CORS 问题;
GitHub Pages 与本地双击打开均可直接渲染.

Usage:
  python scripts/generate_dashboard.py --data data/ --output dashboard/
"""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import date as date_cls, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA = ROOT / "data"
DEFAULT_OUT = ROOT / "dashboard"


def load_json(path: Path):
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def find_latest_answers_dir(data_root: Path, history: dict | None = None):
    """Return the answers dir for the current eval.

    Prefers the dir whose name matches the latest eval date recorded in
    leaderboard_history.json, so a stale dir from an older manual run (e.g.
    a pre-schema-change date) can never shadow the current evaluation.
    Falls back to the lexicographically-latest dir when no match is found.
    """
    answers_root = data_root / "answers"
    if not answers_root.exists():
        return None
    dirs = sorted([d for d in answers_root.iterdir() if d.is_dir()], reverse=True)
    if not dirs:
        return None
    if history:
        eval_dates = [h.get("date") for h in history.get("history", []) if h.get("date")]
        if eval_dates:
            latest_eval = eval_dates[-1]
            for d in dirs:
                if d.name == latest_eval:
                    return d
    return dirs[0]


def build_matrix(latest_dir: Path | None):
    """Return (questions, models, matrix) where matrix[qid][model] = {status, detail}."""
    if latest_dir is None:
        return [], [], {}
    vpath = latest_dir / "verifications.jsonl"
    if not vpath.exists():
        return [], [], {}
    questions = {}
    models = set()
    matrix: dict = {}
    with open(vpath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            qid = r["qid"]
            questions[qid] = {
                "qid": qid,
                "domain": r.get("domain", ""),
                "question": r.get("question", ""),
            }
            models.add(r["model"])
            matrix.setdefault(qid, {})[r["model"]] = {
                "status": r.get("status", "?"),
                "detail": r.get("detail", ""),
            }
    qs = [questions[k] for k in sorted(questions)]
    return qs, sorted(models), matrix


def build_answers(latest_dir: Path | None):
    """Map 'qid|model' -> {answer, n, counts} for drill-down."""
    out: dict = {}
    if latest_dir is None:
        return out
    apath = latest_dir / "answers.jsonl"
    if not apath.exists():
        return out
    with open(apath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            key = f"{r['qid']}|{r['model']}"
            out[key] = {
                "answer": r.get("answer", ""),
                "n": r.get("n_samples", 1),
                "counts": r.get("counts", {}),
            }
    return out


def generate(data_root: Path, out_dir: Path, stale: bool = False):
    history = load_json(data_root / "leaderboard_history.json") or {
        "updated_at": date_cls.today().isoformat(), "models": [], "domains": [], "history": []}
    metadata = (load_json(data_root / "model_metadata.json")
                or load_json(ROOT / "config" / "model_metadata.json")
                or {})
    latest_dir = find_latest_answers_dir(data_root, history)
    questions, matrix_models, matrix = build_matrix(latest_dir)
    answers = build_answers(latest_dir)

    models = list(history.get("models", []))
    for m in matrix_models:
        if m not in models:
            models.append(m)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stale": stale,
        "updated_at": history.get("updated_at", date_cls.today().isoformat()),
        "models": models,
        "domains": history.get("domains", []),
        "history": history.get("history", []),
        "metadata": metadata,
        "matrix": {
            "questions": questions,
            "models": matrix_models,
            "data": matrix,
            "date": latest_dir.name if latest_dir else None,
        },
        "answers": answers,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "dashboard.js").write_text(JS, encoding="utf-8")
    (out_dir / "style.css").write_text(CSS, encoding="utf-8")
    # Critical: GitHub Pages would otherwise run Jekyll on this static site
    # (which can mangle/drop the embedded data/ assets and break the build).
    # peaceiris/actions-gh-pages force-orphans gh-pages from this output dir on
    # every deploy, so .nojekyll MUST live inside the output to survive.
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")

    html = HTML_TEMPLATE.replace("/*__WATCH_DATA__*/", json.dumps(payload, ensure_ascii=False))
    (out_dir / "index.html").write_text(html, encoding="utf-8")

    # Freshness metadata (consumed by the dashboard + by external freshness checks)
    status = {
        "generated_at": payload["generated_at"],
        "data_date": payload["matrix"]["date"],
        "models": len(models),
        "questions": len(questions),
        "history_weeks": len(payload["history"]),
        "disclaimer": "本看板数值度量模型引注与策展基准条文的一致性，不构成法律意见；引注基准由 AI 策展 + 内部复核（不署名、非执业背书、不担责）整理，仍可能存在错误或遗漏，非专业鉴证。对外引用 HVI / CRFI 等数值或结论时，请注明「AI 策展，未经执业背书」，风险自担。",
        "ground_truth_status": "ai_curated_internal_review",
    }
    (out_dir / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")

    # Embed the eval data into the published dashboard so the site is fully
    # self-contained on gh-pages: audit/download links use relative paths and
    # no longer depend on the main branch (which no longer stores generated
    # artifacts). Generated artifacts are published to gh-pages only.
    if data_root.exists():
        dest = out_dir / "data"
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(data_root, dest)
        print(f"[dashboard] embedded data/ -> {dest} (self-contained site)")

    print(f"[dashboard] wrote {out_dir / 'index.html'} ({len(payload['history'])} weeks, "
          f"{len(models)} models, {len(questions)} questions in matrix)")
    return payload


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Legal AI Watch — 法律大模型引注幻觉率实时监测</title>
<meta name="description" content="中国法律大模型法条引注幻觉率(HVI)每周自动监测排行榜">
<link rel="stylesheet" href="style.css">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
</head>
<body>
<div class="legal-disclaimer" role="note">
  ⚠️ <b>非法律意见 · 演示/AI整理基准</b>：本看板数值为「模型引注与策展基准条文的一致性」度量，<b>不构成法律意见</b>；
  引注基准（ground truth）由 <b>AI 策展 + 内部复核</b>（不署名、非执业背书、不担责）整理，仍可能存在错误或遗漏。对外引用任何 HVI / CRFI 数值或结论时，请注明「AI 策展，未经执业背书」，<b>风险自担</b>。
</div>
<header class="site-header">
  <div class="wrap">
    <div class="brand">
      <span class="logo">⚖️</span>
      <div>
        <h1>Legal AI Watch</h1>
        <p class="tagline">中国法律大模型引注准确性实时监测 · 每周自动更新</p>
      </div>
    </div>
    <p class="updated">数据截至: <span id="data-date">—</span> ·
      生成于 <span id="gen-date">—</span>
      <span id="stale-warn" class="stale-warn" style="display:none">⚠ 数据已超过 14 天未更新，可能已失效</span>
    </p>
  </div>
</header>

<div id="eval-fail-banner" class="eval-fail-banner" role="alert" style="display:none">
  ⚠ <b>本周度评测未成功运行</b>：当前展示的是 <b>最近一次成功评测的快照（数据截至 <span id="stale-date">—</span>）</b>。本次失败详情见仓库 <a href="https://github.com/vickywu97/legal-ai-watch/issues?q=label%3Aeval-failed" target="_blank" rel="noopener">Issues（标签 eval-failed）</a>。数值仍具参考性，但可能不是最新。
</div>

<main class="wrap">
  <section class="cards" id="kpi-cards"></section>

  <div class="grid-2">
    <section class="panel">
      <h2>引注幻觉率排行榜 <span class="sub">(HVI · 越低越好)</span></h2>
      <div class="table-scroll">
        <table id="leaderboard">
          <thead><tr>
            <th>排名</th><th>模型</th><th class="num">HVI</th>
            <th class="num">CRFI</th><th class="num">覆盖率</th>
            <th class="num">综合正确</th><th class="num">时序幻觉</th>
            <th class="num">API错误</th><th>厂商 / 版本</th>
          </tr></thead>
          <tbody></tbody>
        </table>
      </div>
      <p class="note">HVI=错引/(正确+错引)；覆盖率=(正确+错引)/(全部)；综合正确=正确/全部（逃避引注被计为不正确）；时序幻觉=引用已废止旧法比例；API错误=接口调用失败次数（基础设施问题，单列，不混入模型行为）。</p>
    </section>

    <section class="panel">
      <h2>HVI 趋势</h2>
      <div class="chart-box"><canvas id="trend-chart"></canvas></div>
    </section>
  </div>

  <section class="panel">
    <h2>与上期对比 <span class="sub" id="diff-sub"></span></h2>
    <div id="diff-view" class="diff-view"></div>
  </section>

  <section class="panel">
    <h2>分领域引注幻觉率 <span class="sub">(最新一期)</span></h2>
    <div class="chart-box"><canvas id="domain-chart"></canvas></div>
  </section>

  <section class="panel">
    <h2>逐题诊断矩阵 <span class="sub" id="matrix-date"></span></h2>
    <p class="legend">
      <span class="lg ok">✓ 正确</span>
      <span class="lg bad">✗MA 错引真实法条</span>
      <span class="lg bad">✗NF 引注法条不存在(NOT_FOUND)</span>
      <span class="lg warn">✗F 内容不忠实(引对条文但表述失真)</span>
      <span class="lg bad">✗T 时序幻觉(引已废止旧法)</span>
      <span class="lg err">✗ERR 接口失败</span>
      <span class="lg unk">? 无法判定</span>
      <span class="lg na">· 未作答</span>
    </p>
    <p class="legend">点击单元格可展开查看该模型对此题的<strong>原始回答</strong>。</p>
    <div class="table-scroll"><div id="matrix"></div></div>
  </section>

  <section class="panel">
    <h2>审计报告</h2>
    <ul id="audit-list" class="audit-list"></ul>
  </section>
</main>

<footer class="site-footer">
  <div class="wrap">
    <p>评测引擎: <a href="https://github.com/vickywu97/legal-hallucination-bench" target="_blank" rel="noopener">legal-hallucination-bench（开源仓库 · MIT）</a>
       · 方法论文档: <a href="https://github.com/vickywu97/legal-ai-watch/blob/main/docs/METHODOLOGY.md" target="_blank" rel="noopener">METHODOLOGY</a>
       · 数据下载: <a href="data/" target="_blank" rel="noopener">data/</a></p>
    <p class="copy">© 2026 Legal AI Watch · MIT License · Built by Vicky Wu</p>
  </div>
</footer>

<script>window.__WATCH__ = /*__WATCH_DATA__*/;</script>
<script src="dashboard.js"></script>
</body>
</html>
"""

CSS = """
:root{
  --bg:#f5f7fa; --panel:#ffffff; --ink:#1f2933; --muted:#647488;
  --line:#e3e8ef; --accent:#2563eb; --accent2:#0f766e;
  --ok:#16a34a; --bad:#dc2626; --unk:#9ca3af; --na:#cbd5e1; --err:#7c3aed;
  --shadow:0 1px 3px rgba(16,24,40,.06),0 1px 2px rgba(16,24,40,.04);
}
*{box-sizing:border-box}
body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",sans-serif;
  background:var(--bg);color:var(--ink);line-height:1.55}
.wrap{max-width:1100px;margin:0 auto;padding:0 20px}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}

.site-header{background:linear-gradient(135deg,#0f172a,#1e3a8a);color:#fff;padding:26px 0}
.brand{display:flex;align-items:center;gap:14px}
.brand .logo{font-size:34px}
.brand h1{margin:0;font-size:24px;letter-spacing:.3px}
.tagline{margin:2px 0 0;color:#c7d2fe;font-size:13px}
.updated{margin:10px 0 0;font-size:13px;color:#cbd5e1}
.stale-warn{display:inline-block;margin-left:8px;padding:2px 8px;border-radius:6px;background:#fef3c7;color:#92400e;font-weight:600}
.eval-fail-banner{margin:0;padding:12px 18px;background:#fffbeb;border-bottom:2px solid #d97706;color:#92400e;font-size:13px;line-height:1.6}
.eval-fail-banner b{color:#78350f}
.eval-fail-banner a{color:#b45309}
.legal-disclaimer{margin:0;padding:12px 18px;background:#fef2f2;border-bottom:2px solid #dc2626;color:#7f1d1d;font-size:13px;line-height:1.6}
.legal-disclaimer b{color:#991b1b}
.site-header .wrap{display:flex;flex-direction:column}

main{padding:24px 0 40px}
.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:22px}
.kpi{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px;box-shadow:var(--shadow)}
.kpi .k-label{font-size:12px;color:var(--muted)}
.kpi .k-value{font-size:26px;font-weight:700;margin-top:4px}
.kpi .k-sub{font-size:12px;color:var(--muted);margin-top:2px}

.grid-2{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-bottom:18px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px;box-shadow:var(--shadow);margin-bottom:18px}
.panel h2{margin:0 0 14px;font-size:17px}
.panel h2 .sub{font-size:12px;color:var(--muted);font-weight:400}
.note{font-size:11px;color:var(--muted);margin:10px 0 0;line-height:1.5}

.table-scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:14px}
th,td{padding:9px 10px;text-align:left;border-bottom:1px solid var(--line);white-space:nowrap}
th{font-size:12px;color:var(--muted);font-weight:600;text-transform:uppercase;letter-spacing:.4px}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
tbody tr:hover{background:#f8fafc}
.rank-badge{display:inline-flex;width:22px;height:22px;align-items:center;justify-content:center;border-radius:50%;background:#eef2ff;color:#3730a3;font-weight:700;font-size:12px}
.hvi-pill{display:inline-block;min-width:46px;text-align:center;padding:3px 8px;border-radius:999px;font-weight:700;color:#fff;font-size:13px}

.chart-box{position:relative;height:340px}

.legend{display:flex;flex-wrap:wrap;gap:10px;font-size:12px;margin:0 0 12px;color:var(--muted)}
.lg{padding:2px 8px;border-radius:6px;background:#f1f5f9}
.lg.ok{color:var(--ok)} .lg.bad{color:var(--bad)} .lg.unk{color:var(--unk)} .lg.na{color:#94a3b8} .lg.err{color:var(--err)} .lg.warn{color:#b45309}

#matrix{display:inline-block;min-width:100%}
table.matrix{border-collapse:collapse;font-size:13px}
table.matrix th,table.matrix td{border:1px solid var(--line);padding:6px 8px;text-align:center}
table.matrix th.q{text-align:left;min-width:220px;max-width:340px;white-space:normal;color:var(--ink);font-weight:500}
table.matrix thead th{background:#f8fafc;position:sticky;top:0}
.cell{font-weight:700;border-radius:4px;cursor:pointer;display:block;padding:4px 6px}
.cell.ok{background:#dcfce7;color:var(--ok)}
.cell.bad{background:#fee2e2;color:var(--bad)}
.cell.temporal{background:#fae8ff;color:#a21caf}
.cell.warn{background:#fef3c7;color:#b45309}
.cell.err{background:#ede9fe;color:var(--err)}
.cell.unk{background:#f3f4f6;color:var(--unk)}
.cell.na{background:#f1f5f9;color:#94a3b8}
.cell .tip{display:block;font-weight:400;font-size:10px;color:var(--muted);margin-top:2px;max-width:160px;white-space:normal}
.ans{font-size:12px;color:var(--ink);background:#f8fafc;border:1px solid var(--line);border-radius:6px;padding:8px;margin-top:4px;text-align:left;white-space:normal;line-height:1.5}
.ans.collapsed{display:none}

.diff-view{display:flex;flex-direction:column;gap:8px}
.diff-row{display:flex;align-items:center;gap:12px;font-size:14px;padding:6px 8px;border:1px solid var(--line);border-radius:8px}
.diff-model{font-weight:600;min-width:120px}
.diff-bar{flex:1;height:8px;background:#eef2f7;border-radius:4px;overflow:hidden}
.diff-bar > span{display:block;height:100%}
.diff-delta{font-weight:700;min-width:64px;text-align:right;font-variant-numeric:tabular-nums}

.audit-list{margin:0;padding-left:18px;font-size:14px}
.audit-list li{margin:6px 0}

.site-footer{border-top:1px solid var(--line);padding:22px 0;color:var(--muted);font-size:13px}
.site-footer .copy{margin-top:6px;font-size:12px}

@media(max-width:860px){
  .cards{grid-template-columns:repeat(2,1fr)}
  .grid-2{grid-template-columns:1fr}
}
"""

JS = """
(function () {
  const W = window.__WATCH__ || {};
  const MODELS = W.models || [];
  const HISTORY = W.history || [];
  const META = W.metadata || {};
  const DOMAINS = W.domains || [];
  const ANSWERS = W.answers || {};

  const PALETTE = ["#2563eb","#0f766e","#d97706","#db2777","#7c3aed","#0891b2","#ca8a04","#16a34a"];
  const colorFor = (i) => PALETTE[i % PALETTE.length];

  function pct(x){ return ((x==null?0:x)*100).toFixed(0) + "%"; }
  function num(x, d=0){ return x==null ? "—" : (d? x.toFixed(d) : x); }
  function hviColor(h){
    if (h == null) return "#94a3b8";
    if (h <= 0.15) return "#16a34a";
    if (h <= 0.35) return "#d97706";
    if (h <= 0.55) return "#ea580c";
    return "#dc2626";
  }
  function statusClass(st){
    if (st === "✓") return "ok";
    if (st === "✗ERR") return "err";
    if (st === "✗T") return "temporal";
    if (st === "✗NF") return "bad"; // 引注法条不存在
    if (st === "✗F") return "warn"; // 内容不忠实
    if (["?","·"].includes(st)) return st === "·" ? "na" : "unk";
    return "bad"; // ✗MA
  }

  // ---- header / freshness ----
  const dataDate = W.matrix && W.matrix.date ? W.matrix.date : (HISTORY.length ? HISTORY[HISTORY.length-1].date : null);
  document.getElementById("data-date").textContent = dataDate || "—";
  document.getElementById("gen-date").textContent = (W.generated_at || "").slice(0,10) || "—";
  if (dataDate) {
    const days = Math.floor((Date.now() - new Date(dataDate).getTime()) / 86400000);
    if (days > 14) document.getElementById("stale-warn").style.display = "inline-block";
  }
  if (W.stale) {
    const b = document.getElementById("eval-fail-banner");
    if (b) b.style.display = "block";
    const sd = document.getElementById("stale-date");
    if (sd) sd.textContent = dataDate || "—";
  }

  // ---- KPI cards (latest week) ----
  const latest = HISTORY.length ? HISTORY[HISTORY.length - 1] : null;
  const kpiBox = document.getElementById("kpi-cards");
  if (latest) {
    const allRows = latest.leaderboard || [];
    const lb = allRows.filter(r => r.hvi != null);
    const best = lb[0], worst = lb[lb.length - 1];
    const avg = lb.length ? lb.reduce((s,r)=>s+r.hvi,0)/lb.length : 0;
    const avgCov = lb.length ? lb.reduce((s,r)=>s+(r.coverage||0),0)/lb.length : 0;
    const cards = [
      {label:"参评模型", value: lb.length, sub:"本周活跃"},
      {label:"最低 HVI (最佳)", value: best?pct(best.hvi):"—", sub: best?best.model:"—"},
      {label:"最高 HVI (最差)", value: worst?pct(worst.hvi):"—", sub: worst?worst.model:"—"},
      {label:"平均 HVI / 覆盖率", value: pct(avg), sub:"覆盖率 "+pct(avgCov)},
    ];
    kpiBox.innerHTML = cards.map(c=>`<div class="kpi"><div class="k-label">${c.label}</div><div class="k-value">${c.value}</div><div class="k-sub">${c.sub}</div></div>`).join("");
  }

  // ---- leaderboard table (latest week) ----
  const tbody = document.querySelector("#leaderboard tbody");
  if (latest) {
    tbody.innerHTML = (latest.leaderboard||[]).map((r,i)=>{
      const m = META[r.model] || {};
      const mv = [m.vendor, m.version].filter(Boolean).join(" · ") || "—";
      const rankCell = (r.rank==null) ? "—" : r.rank;
      const hviCell = (r.hvi==null)
        ? `<span class="hvi-pill" style="background:#94a3b8">未作答</span>`
        : `<span class="hvi-pill" style="background:${hviColor(r.hvi)}">${pct(r.hvi)}</span>`;
      return `<tr>
        <td><span class="rank-badge">${rankCell}</span></td>
        <td><strong>${r.model}</strong></td>
        <td class="num">${hviCell}</td>
        <td class="num">${num(r.crfi!=null?pct(r.crfi):null)}</td>
        <td class="num">${num(r.coverage!=null?pct(r.coverage):null)}</td>
        <td class="num">${num(r.integrity!=null?pct(r.integrity):null)}</td>
        <td class="num">${num(r.temporal!=null?pct(r.temporal):null)}</td>
        <td class="num">${r.api_errors||0}</td>
        <td>${mv}</td>
      </tr>`;
    }).join("");
  }

  // ---- diff vs previous week ----
  const diffEl = document.getElementById("diff-view");
  if (HISTORY.length >= 2) {
    const cur = HISTORY[HISTORY.length-1], prev = HISTORY[HISTORY.length-2];
    document.getElementById("diff-sub").textContent = `( ${prev.date} → ${cur.date} )`;
    const prevMap = {}; (prev.leaderboard||[]).forEach(r=> prevMap[r.model]=r);
    const rows = (cur.leaderboard||[]).filter(r=>r.hvi!=null && prevMap[r.model] && prevMap[r.model].hvi!=null)
      .map(r=>{
        const d = (r.hvi - prevMap[r.model].hvi) * 100; // percentage points
        const up = d > 0.5, down = d < -0.5;
        const color = up ? "#dc2626" : down ? "#16a34a" : "#94a3b8";
        const arrow = up ? "▲" : down ? "▼" : "—";
        const w = Math.min(100, Math.abs(d)*4);
        return `<div class="diff-row">
          <span class="diff-model">${r.model}</span>
          <span class="diff-bar"><span style="width:${w}%;background:${color}"></span></span>
          <span class="diff-delta" style="color:${color}">${arrow} ${Math.abs(d).toFixed(1)}pp</span>
        </div>`;
      });
    diffEl.innerHTML = rows.length ? rows.join("") : '<p style="color:#647488">无可对比数据。</p>';
  } else if (diffEl) {
    diffEl.innerHTML = '<p style="color:#647488">需至少两期数据方可对比。</p>';
  }

  // ---- trend chart ----
  if (document.getElementById("trend-chart") && HISTORY.length) {
    const dates = HISTORY.map(h=>h.date);
    const datasets = MODELS.map((m,i)=>{
      const data = HISTORY.map(h=>{
        const row = (h.leaderboard||[]).find(r=>r.model===m);
        return (row && row.hvi != null) ? +(row.hvi*100).toFixed(1) : null;
      });
      return {label:m, data, borderColor:colorFor(i), backgroundColor:colorFor(i),
        tension:.25, spanGaps:true, pointRadius:3};
    });
    new Chart(document.getElementById("trend-chart"), {
      type:"line",
      data:{labels:dates, datasets},
      options:{responsive:true, maintainAspectRatio:false,
        plugins:{legend:{position:"bottom"}, title:{display:false},
          tooltip:{callbacks:{label:(c)=>`${c.dataset.label}: ${c.parsed.y}%`}}},
        scales:{y:{title:{display:true,text:"HVI (%)"}, ticks:{callback:v=>v+"%"}},
                x:{ticks:{maxRotation:45,minRotation:0}}}}
    });
  }

  // ---- domain bar chart (latest week) ----
  if (document.getElementById("domain-chart") && latest) {
    const dh = latest.domain_hvi || {};
    const doms = DOMAINS.length ? DOMAINS : (Object.values(dh)[0] ? Object.keys(Object.values(dh)[0]) : []);
    const datasets = MODELS.map((m,i)=>({
      label:m, data:doms.map(d=> dh[m] && dh[m][d]!=null ? +(dh[m][d]*100).toFixed(1) : 0),
      backgroundColor:colorFor(i)
    }));
    new Chart(document.getElementById("domain-chart"), {
      type:"bar",
      data:{labels:doms, datasets},
      options:{responsive:true, maintainAspectRatio:false,
        plugins:{legend:{position:"bottom"}, tooltip:{callbacks:{label:(c)=>`${c.dataset.label}: ${c.parsed.y}%`}}},
        scales:{y:{title:{display:true,text:"HVI (%)"}, ticks:{callback:v=>v+"%"}}}}
    });
  }

  // ---- matrix (with answer drill-down) ----
  const M = W.matrix || {};
  const mDate = document.getElementById("matrix-date");
  if (mDate) mDate.textContent = M.date ? "( "+M.date+" )" : "";
  const mq = M.questions || [];
  const mm = M.models || [];
  const md = M.data || {};
  const matrixEl = document.getElementById("matrix");
  if (matrixEl && mq.length) {
    let html = '<table class="matrix"><thead><tr><th class="q">题目 / 法域</th>';
    mm.forEach(m=> html += `<th>${m}</th>`);
    html += "</tr></thead><tbody>";
    mq.forEach(q=>{
      html += `<tr><td class="q"><strong>Q${q.qid}</strong> · ${q.domain}<br><span style="color:#647488;font-size:12px">${q.question}</span></td>`;
      mm.forEach(m=>{
        const cell = (md[q.qid]||{})[m] || {status:"?"};
        const st = cell.status;
        const cls = statusClass(st);
        const tip = cell.detail ? `<span class="tip">${cell.detail}</span>` : "";
        const akey = q.qid + "|" + m;
        const ansObj = ANSWERS[akey];
        const ansHtml = ansObj && ansObj.answer
          ? `<div class="ans collapsed" id="ans-${akey}">${ansObj.answer.replace(/</g,"&lt;")}</div>` : "";
        html += `<td><span class="cell ${cls}" onclick="document.getElementById('ans-${akey}').classList.toggle('collapsed')">${st}</span>${tip}${ansHtml}</td>`;
      });
      html += "</tr>";
    });
    html += "</tbody></table>";
    matrixEl.innerHTML = html;
  } else if (matrixEl) {
    matrixEl.innerHTML = '<p style="color:#647488">本轮暂无逐题核验数据（演示数据未生成）。运行 <code>python scripts/seed_demo.py</code> 后重新生成。</p>';
  }

  // ---- audit list ----
  const audit = document.getElementById("audit-list");
  if (audit && latest) {
    const d = latest.date;
    audit.innerHTML = MODELS.map(m=>
      `<li><a href="data/answers/${d}/verifications.jsonl" target="_blank" rel="noopener">${m} (${d})</a> — 原始回答与核验逐条记录</li>`
    ).join("");
  }
})();
"""


def main():
    ap = argparse.ArgumentParser(description="Generate Legal AI Watch dashboard")
    ap.add_argument("--data", default=str(DEFAULT_DATA), help="data root")
    ap.add_argument("--output", default=str(DEFAULT_OUT), help="dashboard output dir")
    ap.add_argument("--stale", action="store_true",
                    help="Mark the dashboard as serving last-good (stale) data because the "
                         "latest evaluation failed; renders a visitor-facing banner.")
    args = ap.parse_args()
    generate(Path(args.data), Path(args.output), stale=args.stale)


if __name__ == "__main__":
    main()
