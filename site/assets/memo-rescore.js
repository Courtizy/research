// Study 01b memo: every number and sentence with a number comes from ../data/forecast_accuracy_rescore.json.
const $ = (id) => document.getElementById(id);
const li = (items) => items.map((x) => `<li>${x}</li>`).join("");

fetch("../data/forecast_accuracy_rescore.json")
  .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
  .then((d) => {
    const s = d.sample;
    $("memo-meta").textContent = `Jason C. Courtoy · results run ${d.as_of} · engine ${d.engine}` +
      (d.panels_engine ? ` · filings read by ${d.panels_engine}` : "");
    $("m-lead").textContent = d.headline.lead;
    $("m-sub").textContent = d.headline.sub;
    $("m-sample").textContent = `${s.companies_scored} companies, ${s.observations.toLocaleString()} forecast–outcome pairs, ` +
      `base years ${s.base_years[0]}–${s.base_years[1]}; ranges scored on ${s.range_test.observations.toLocaleString()} forecasts ` +
      `from base year ${s.range_test.first_base_year} on.`;
    $("m-findings").innerHTML = li((d.memo?.findings || []).map((f) => `<strong>${f.label}.</strong> ${f.text}`));
    $("m-practice").innerHTML = li((d.memo?.practice || []).map((p) => `<strong>${p.title}</strong> ${p.text}`)) || "<li>No practice point cleared the evidence bar.</li>";
  }, () => { $("m-lead").textContent = "Results aren't published yet."; });
