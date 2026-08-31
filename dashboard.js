
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
    if (["?","·"].includes(st)) return st === "·" ? "na" : "unk";
    return "bad"; // ✗MA / ✗T
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
