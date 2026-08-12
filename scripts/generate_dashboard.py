#!/usr/bin/env python3
"""
generate_dashboard.py — 由 data/ 生成静态 Dashboard (dashboard/index.html)

读取:
  data/leaderboard_history.json   (排行榜历史, 趋势图 & 主表)
  data/model_metadata.json        (模型厂商/版本等元数据)
  data/answers/<最新日期>/verifications.jsonl  (逐题诊断矩阵)

产出:
  dashboard/index.html   内联数据 + 引入 style.css / dashboard.js / Chart.js(CDN)
  dashboard/style.css
  dashboard/dashboard.js

数据以内联 JSON (window.__WATCH__) 形式写入 HTML, 避免本地预览的 fetch/CORS 问题;
GitHub Pages 与本地双击打开均可直接渲染。

Usage:
  python scripts/generate_dashboard.py --data data/ --output dashboard/
"""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import date as date_cls
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA = ROOT / "data"
DEFAULT_OUT = ROOT / "dashboard"


def load_json(path: Path):
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def find_latest_answers_dir(data_root: Path):
    answers_root = data_root / "answers"
    if not answers_root.exists():
        return None
    dirs = sorted([d for d in answers_root.iterdir() if d.is_dir()], reverse=True)
    return dirs[0] if dirs else None


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


def generate(data_root: Path, out_dir: Path):
    history = load_json(data_root / "leaderboard_history.json") or {
        "updated_at": date_cls.today().isoformat(), "models": [], "domains": [], "history": []}
    # Model vendor/version metadata lives in config/ (source), with a fallback
    # to a data/-side copy for backward compatibility.
    metadata = (load_json(data_root / "model_metadata.json")
                or load_json(ROOT / "config" / "model_metadata.json")
                or {})
    latest_dir = find_latest_answers_dir(data_root)
    questions, matrix_models, matrix = build_matrix(latest_dir)

    # Coalesce model ordering: prefer history.models, append any from matrix
    models = list(history.get("models", []))
    for m in matrix_models:
        if m not in models:
            models.append(m)

    payload = {
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
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "dashboard.js").write_text(JS, encoding="utf-8")
    (out_dir / "style.css").write_text(CSS, encoding="utf-8")

    html = HTML_TEMPLATE.replace("/*__WATCH_DATA__*/", json.dumps(payload, ensure_ascii=False))
    (out_dir / "index.html").write_text(html, encoding="utf-8")

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
<header class="site-header">
  <div class="wrap">
    <div class="brand">
      <span class="logo">⚖️</span>
      <div>
        <h1>Legal AI Watch</h1>
        <p class="tagline">中国法律大模型引注准确性实时监测 · 每周自动更新</p>
      </div>
    </div>
    <p class="updated">最后更新: <span id="last-updated">—</span></p>
  </div>
</header>

<main class="wrap">
  <section class="cards" id="kpi-cards"></section>

  <div class="grid-2">
    <section class="panel">
      <h2>引注幻觉率排行榜 <span class="sub">(HVI · 越低越好)</span></h2>
      <div class="table-scroll">
        <table id="leaderboard">
          <thead><tr>
            <th>排名</th><th>模型</th><th class="num">HVI</th>
            <th class="num">引注数</th><th class="num">CRFI</th>
            <th class="num">时序幻觉</th><th>厂商 / 版本</th>
          </tr></thead>
          <tbody></tbody>
        </table>
      </div>
    </section>

    <section class="panel">
      <h2>近 12 周 HVI 趋势</h2>
      <div class="chart-box"><canvas id="trend-chart"></canvas></div>
    </section>
  </div>

  <section class="panel">
    <h2>分领域引注幻觉率 <span class="sub">(最新一期)</span></h2>
    <div class="chart-box"><canvas id="domain-chart"></canvas></div>
  </section>

  <section class="panel">
    <h2>逐题诊断矩阵 <span class="sub" id="matrix-date"></span></h2>
    <p class="legend">
      <span class="lg ok">✓ 正确</span>
      <span class="lg bad">✗MA 编造法条</span>
      <span class="lg bad">✗NF 内容不符</span>
      <span class="lg bad">✗F 事实错误</span>
      <span class="lg unk">? 无法判定</span>
      <span class="lg na">· 未作答</span>
    </p>
    <div class="table-scroll"><div id="matrix"></div></div>
  </section>

  <section class="panel">
    <h2>审计报告</h2>
    <ul id="audit-list" class="audit-list"></ul>
  </section>
</main>

<footer class="site-footer">
  <div class="wrap">
    <p>评测引擎: <a href="https://github.com/vickywu97/legal-hallucination-bench" target="_blank" rel="noopener">legal-hallucination-bench</a>
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
  --ok:#16a34a; --bad:#dc2626; --unk:#9ca3af; --na:#cbd5e1;
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
.lg.ok{color:var(--ok)} .lg.bad{color:var(--bad)} .lg.unk{color:var(--unk)} .lg.na{color:#94a3b8}

#matrix{display:inline-block;min-width:100%}
table.matrix{border-collapse:collapse;font-size:13px}
table.matrix th,table.matrix td{border:1px solid var(--line);padding:6px 8px;text-align:center}
table.matrix th.q{text-align:left;min-width:220px;max-width:340px;white-space:normal;color:var(--ink);font-weight:500}
table.matrix thead th{background:#f8fafc;position:sticky;top:0}
.cell{font-weight:700;border-radius:4px}
.cell.ok{background:#dcfce7;color:var(--ok)}
.cell.bad{background:#fee2e2;color:var(--bad)}
.cell.unk{background:#f3f4f6;color:var(--unk)}
.cell.na{background:#f1f5f9;color:#94a3b8}
.cell .tip{display:block;font-weight:400;font-size:10px;color:var(--muted);margin-top:2px;max-width:160px;white-space:normal}

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

  // stable color per model
  const PALETTE = ["#2563eb","#0f766e","#d97706","#db2777","#7c3aed","#0891b2","#ca8a04","#16a34a"];
  const colorFor = (i) => PALETTE[i % PALETTE.length];

  function pct(x){ return ((x==null?0:x)*100).toFixed(0) + "%"; }
  function hviColor(h){ // red high, green low
    if (h <= 0.15) return "#16a34a";
    if (h <= 0.35) return "#d97706";
    if (h <= 0.55) return "#ea580c";
    return "#dc2626";
  }

  // ---- header ----
  document.getElementById("last-updated").textContent = W.updated_at || "—";

  // ---- KPI cards (latest week) ----
  const latest = HISTORY.length ? HISTORY[HISTORY.length - 1] : null;
  const kpiBox = document.getElementById("kpi-cards");
  if (latest) {
    const allRows = latest.leaderboard || [];
    const lb = allRows.filter(r => r.hvi != null);   // ranked (answered) models only
    const best = lb[0];
    const worst = lb[lb.length - 1];
    const avg = lb.length ? lb.reduce((s,r)=>s+r.hvi,0)/lb.length : 0;
    const cards = [
      {label:"参评模型", value: lb.length, sub:"本周活跃"},
      {label:"最低 HVI (最佳)", value: best?pct(best.hvi):"—", sub: best?best.model:"—"},
      {label:"最高 HVI (最差)", value: worst?pct(worst.hvi):"—", sub: worst?worst.model:"—"},
      {label:"平均 HVI", value: pct(avg), sub:"全模型均值"},
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
        <td class="num">${r.citations}</td>
        <td class="num">${pct(r.crfi||0)}</td>
        <td class="num">${pct(r.temporal||0)}</td>
        <td>${mv}</td>
      </tr>`;
    }).join("");
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

  // ---- matrix ----
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
        const cls = ["✓"].includes(st)?"ok":["?","·"].includes(st)?(st==="·"?"na":"unk"):"bad";
        const tip = cell.detail ? `<span class="tip">${cell.detail}</span>` : "";
        html += `<td><span class="cell ${cls}">${st}</span>${tip}</td>`;
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
    args = ap.parse_args()
    generate(Path(args.data), Path(args.output))


if __name__ == "__main__":
    main()
