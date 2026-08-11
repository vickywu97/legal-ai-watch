
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
      `<li><a href="https://github.com/vickywu97/legal-ai-watch/blob/main/data/answers/${d}/verifications.jsonl" target="_blank" rel="noopener">${m} (${d})</a> — 原始回答与核验逐条记录</li>`
    ).join("");
  }
})();
