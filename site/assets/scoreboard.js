// Forward scoreboard: every number comes from ../data/scoreboard.json, written by the weekly run.
const $ = (id) => document.getElementById(id);
const pct = (x) => `${Math.round(x * 100)}%`;

fetch("../data/scoreboard.json")
  .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
  .then((d) => {
    $("sb-meta").textContent = `Engine ${d.engine} · frozen ${d.frozen_on}` + (d.checked_at ? ` · last checked ${d.checked_at.slice(0, 10)}` : "");
    $("sb-frozen").textContent = d.frozen_on;
    const items = [
      d.forecasts
        ? `${d.forecasts} forecasts logged for ${d.companies} companies, filed ${d.first_filed} to ${d.last_filed}.`
        : "No forecast logged yet: the first come with 10-Ks filed after the freeze.",
      d.log_intact ? "The log's hash chain is intact." : "The log's hash chain is broken: an earlier entry was changed.",
      d.scored.length ? `Scored so far: ${d.scored.reduce((a, s) => a + s.n, 0)} forecast-year pairs.`
        : "Nothing scored yet. One-year scores arrive as these companies file their next 10-K, from late 2027.",
    ];
    $("sb-status").innerHTML = items.map((x) => `<li>${x}</li>`).join("");
    if (d.scored.length) {
      $("sb-table").innerHTML = `<table><thead><tr><th>Years out</th><th>Scored</th><th>Median miss</th>` +
        `<th>Inside 80%</th><th>Inside 90%</th><th>Beats no change</th></tr></thead><tbody>` +
        d.scored.map((s) => `<tr><td>${s.h}</td><td>${s.n}</td><td>${pct(s.median_miss)}</td><td>${pct(s.inside_80)}</td>` +
          `<td>${pct(s.inside_90)}</td><td>${pct(s.beats_no_change)}</td></tr>`).join("") + `</tbody></table>`;
    }
  }, () => { $("sb-status").innerHTML = "<li>The scoreboard isn't published yet.</li>"; });
