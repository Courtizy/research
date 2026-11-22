// Memo page: every number and sentence with a number comes from ../data/forecast_accuracy.json and ../data/held_out.json.
const $ = (id) => document.getElementById(id);
const li = (items) => items.map((x) => `<li>${x}</li>`).join("");

fetch("../data/forecast_accuracy.json")
  .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
  .then((d) => {
    const s = d.sample;
    $("memo-meta").textContent = `Jason C. Courtoy · results run ${d.as_of} · engine ${d.engine}`;
    $("m-lead").textContent = d.headline.lead;
    $("m-sub").textContent = d.headline.sub;
    $("m-sample").textContent = `${s.companies_scored} companies, ${s.observations.toLocaleString()} forecast–outcome pairs, ` +
      `base years ${s.base_years[0]}–${s.base_years[1]}, drawn from the largest US filers in 2011, 2015 and 2019 ` +
      `(including firms that later disappeared).`;
    $("m-findings").innerHTML = li(d.headline.findings.map((f) => `<strong>${f.label}.</strong> ${f.text}`));
    $("m-practice").innerHTML = li(d.memo.practice.map((p) => `<strong>${p.title}</strong> ${p.text}`)) || "<li>No practice point cleared the evidence bar.</li>";
    $("m-changes").innerHTML = li(d.memo.valuation_model) || "<li>No change indicated.</li>";
  }, () => { $("m-lead").textContent = "Results aren't published yet."; });

fetch("../data/held_out.json")
  .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
  .then((h) => {
    const pct = (x) => `${Math.round(x * 100)}%`;
    const v = Object.fromEntries(h.ranges_by_volatility.map((g) => [g.group, g["80"]]));
    const s = h.sample;
    $("m-held-sample").textContent = `${s.companies_scored} US filers with $250M to $1B of revenue in 2011, 2015 or 2019, ` +
      `none of them in the main sample, drawn by a fixed rule`;
    $("m-held-out").innerHTML = li([
      h.headline.lead,
      ...h.headline.notes,
      `By volatility, the 80% range held ${pct(v.steady)} for the steadiest third of held-out companies and ` +
        `${pct(v.volatile)} for the most volatile third.`,
    ]);
  }, () => { $("m-held-out").innerHTML = "<li>The held-out results aren't published yet.</li>"; });
