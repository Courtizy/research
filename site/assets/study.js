// Study page: shows ../data/<study>.json. No model math here; every number comes from the study run.
import { series, plotlyLayout, onModeChange } from "../brand/js/palette.js";

const app = document.documentElement.dataset.app;
const NAMES = { naive: "No change", hist3: "Own history", sector: "Sector", model: "Model" };
const ORDER = ["model", "hist3", "sector", "naive"];
const $ = (id) => document.getElementById(id);
const pct = (x, d = 0) => (x == null ? "–" : `${(x * 100).toFixed(d)}%`);
const num = (x, d = 3) => (x == null ? "–" : x.toFixed(d));

function tabs() {
  const show = (name) => {
    document.querySelectorAll(".tab").forEach((t) => t.setAttribute("aria-selected", t.dataset.tab === name));
    document.querySelectorAll("[data-panel]").forEach((p) => (p.hidden = p.dataset.panel !== name));
  };
  document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => { show(t.dataset.tab); history.replaceState(null, "", `#${t.dataset.tab}`); }));
  document.querySelectorAll("[data-goto]").forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); show(a.dataset.goto); history.replaceState(null, "", `#${a.dataset.goto}`); }));
  const h = location.hash.slice(1);
  if (["overview", "results", "method"].includes(h)) show(h);
}

function table(el, head, rows) {
  el.innerHTML = `<thead><tr>${head.map((h) => `<th>${h}</th>`).join("")}</tr></thead>` +
    `<tbody>${rows.map((r) => `<tr>${r.map((c, i) => `<td${i ? ' class="num"' : ""}>${c}</td>`).join("")}</tr>`).join("")}</tbody>`;
}

function render(d) {
  $("headline").textContent = d.headline.lead;
  $("subhead").textContent = d.headline.sub;
  $("findings").innerHTML = d.headline.findings.map((f) => `<li><strong>${f.label}.</strong> ${f.text}</li>`).join("");
  $("kpis").innerHTML = d.headline.kpis.map((k) => `<div class="kpi"><div class="kpi__value">${k.value}</div><div class="kpi__label">${k.label}</div></div>`).join("");
  const s = d.sample;
  $("sample").textContent = `${s.companies_scored} companies scored, ${s.observations.toLocaleString()} forecast–outcome pairs, base years ${s.base_years[0]}–${s.base_years[1]}. Universe ${s.universe} companies; ${s.excluded_finance} in finance excluded.`;
  $("engine").textContent = `Engine: ${d.engine}. Run ${d.as_of}.`;
  $("generated").textContent = `Results generated ${d.as_of}.`;

  const acc = (m, h) => d.accuracy.find((a) => a.method === m && a.h === h);
  table($("tb-accuracy"), ["Method", "Years out", "Pairs", "Median abs. error", "Bias", "Skill vs no change", "t (vs no change)"],
    ORDER.flatMap((m) => [1, 3, 5].map((h) => acc(m, h)).filter(Boolean).map((a) =>
      [NAMES[m], a.h, a.n.toLocaleString(), num(a.median_abs_error), num(a.bias.mean), m === "naive" ? "–" : pct(a.skill_vs_naive), m === "naive" ? "–" : num(a.loss_diff_vs_naive.t, 1)])));
  table($("tb-coverage"), ["Years out", "Pairs", "Inside P10–P90", "Below", "Above", "p vs 80%"],
    d.coverage.map((c) => [c.h, c.n.toLocaleString(), pct(c.coverage), pct(c.below), pct(c.above), c.p_vs_nominal < 0.001 ? "<0.001" : num(c.p_vs_nominal)]));
  table($("tb-margin"), ["Years out", "Pairs", "No change (pp)", "3-yr mean (pp)", "t (mean − no change)"],
    d.margin.map((m) => [m.h, m.n.toLocaleString(), num(m.median_abs_pp.naive, 1), num(m.median_abs_pp.hist3, 1), num(m.loss_diff_hist3_vs_naive.t, 1)]));
  const r3 = (block) => [block.accuracy.find((a) => a.method === "model" && a.h === 3), block.coverage.find((c) => c.h === 3)];
  const base = [acc("model", 3), d.coverage.find((c) => c.h === 3)];
  const rob = { "All pairs": base, "Large moves removed": r3(d.robustness.no_large_moves),
    "Target year before 2020": r3(d.robustness.targets_before_2020), "Target year 2020 on": r3(d.robustness.targets_2020_on) };
  table($("tb-robust"), ["Sample", "Pairs", "Model skill vs no change", "Model bias", "Range coverage"],
    Object.entries(rob).map(([k, [a, c]]) => [k, a ? a.n.toLocaleString() : "–", a ? pct(a.skill_vs_naive) : "–", a ? num(a.bias.mean) : "–", c ? pct(c.coverage) : "–"]));
  drawCharts(d);
}

function charts(d) {
  const c = series(app);
  const base = { ...plotlyLayout(app), margin: { t: 8, r: 8, b: 80, l: 56 }, legend: { orientation: "h", y: -0.32, x: 0 } };
  const cfg = { displayModeBar: false, responsive: true };
  const H = [1, 2, 3, 4, 5];
  const xH = { title: { text: "Years out" }, dtick: 1 };
  Plotly.react("ch-error", ORDER.map((m, i) => ({
    x: H, y: H.map((h) => (d.accuracy.find((a) => a.method === m && a.h === h) || {}).median_abs_error ?? null),
    name: NAMES[m], mode: "lines+markers", line: { color: c[i], width: m === "model" ? 3 : 2 },
  })), { ...base, xaxis: xH, yaxis: { title: { text: "Median abs. log error" }, rangemode: "tozero" } }, cfg);

  Plotly.react("ch-coverage", [{ x: d.coverage.map((x) => x.h), y: d.coverage.map((x) => x.coverage), type: "bar", name: "Inside P10–P90", marker: { color: c[0] } }],
    { ...base, showlegend: false, xaxis: xH, yaxis: { title: { text: "Coverage" }, range: [0, 1], tickformat: ".0%" },
      shapes: [{ type: "line", xref: "paper", x0: 0, x1: 1, y0: 0.8, y1: 0.8, line: { dash: "dash", width: 2, color: c[2] } }],
      annotations: [{ xref: "paper", x: 1, y: 0.8, text: "promised 80%", showarrow: false, yshift: 10, xanchor: "right" }] }, cfg);

  const g = d.bias_by_growth;
  Plotly.react("ch-bias", ["model", "hist3"].map((m, i) => ({
    x: g.map((r) => r.group), y: g.map((r) => r[m].mean), name: NAMES[m], mode: "markers+lines",
    error_y: { type: "data", array: g.map((r) => 2 * (r[m].se || 0)), visible: true, color: c[i] }, line: { color: c[i], width: 2 },
    customdata: g.map((r) => r.g3_median), hovertemplate: "decile %{x}<br>prior growth %{customdata:.1%}<br>error %{y:.3f}<extra></extra>",
  })), { ...base, xaxis: { title: { text: "Prior growth decile (1 = slowest)" }, dtick: 1 }, yaxis: { title: { text: "Mean log error, 3 yrs out" }, zeroline: true } }, cfg);

  const s = [...d.by_division].sort((a, b) => a.model - b.model);
  Plotly.react("ch-sector", ["model", "hist3"].map((m, i) => ({
    y: s.map((r) => `${r.division} (${r.companies})`), x: s.map((r) => r[m]), name: NAMES[m], mode: "markers", type: "scatter",
    marker: { color: c[i], size: 10 }, orientation: "h",
  })), { ...base, yaxis: { automargin: true }, xaxis: { title: { text: "Skill vs no change" }, tickformat: ".0%", zeroline: true } }, cfg);
}

function drawCharts(d) {
  if (!window.Plotly) return;   // tables and text still work if the chart library fails to load
  charts(d);
}

tabs();
fetch("../data/forecast_accuracy.json")
  .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
  .then((d) => { render(d); onModeChange(() => drawCharts(d)); },
        () => { $("headline").textContent = "Results aren't published yet."; });
