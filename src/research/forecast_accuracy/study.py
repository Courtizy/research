"""The whole study from company panels to the published results document."""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta
from statistics import median

from .methods import sector_forecasts
from .metrics import (accuracy, bias_by_growth, by_division, coverage, division, margin_accuracy,
                      observations)

MIN_SECTOR_PEERS = 5
EXCLUDED_DIVISIONS = {"Finance"}
PEER_STALE_DAYS = 400       # a year plus slack for late filers


def add_sector_forecasts(panels: list[dict]) -> None:
    """Sector growth = median three-year CAGR of the other companies in the same SIC division, each as of
    its latest 10-K filed on or before this origin's filing date (leave-one-out, so a firm never forecasts
    itself). Point in time: a peer's filing made after the origin can't move the forecast. A peer whose
    latest 10-K is more than PEER_STALE_DAYS old has stopped filing and drops out."""
    events: dict[str | None, list[tuple[str, str, float | None]]] = defaultdict(list)
    for p in panels:
        for o in p["origins"]:
            events[division(p.get("sic"))].append((o["origin"], p["cik"], o["g3"]))
    for d, evs in events.items():
        evs.sort()
        todo = sorted(((o["origin"], p["cik"], o) for p in panels if division(p.get("sic")) == d
                       for o in p["origins"]), key=lambda t: t[:2])
        latest: dict[str, tuple[str, float | None]] = {}
        i = 0
        for when, cik, o in todo:
            while i < len(evs) and evs[i][0] <= when:   # every peer filing made by the end of that day
                latest[evs[i][1]] = (evs[i][0], evs[i][2])
                i += 1
            cutoff = (date.fromisoformat(when) - timedelta(days=PEER_STALE_DAYS)).isoformat()
            peers = [g for c, (filed, g) in latest.items() if c != cik and g is not None and filed >= cutoff]
            f = sector_forecasts(o["r0"], median(peers) if len(peers) >= MIN_SECTOR_PEERS else None)
            o["revenue"].pop("sector", None)
            if f:
                o["revenue"]["sector"] = f


def run(panels: list[dict], *, engine: str, as_of: str, universe_size: int) -> dict:
    kept = [p for p in panels if division(p.get("sic")) not in EXCLUDED_DIVISIONS]
    add_sector_forecasts(kept)
    rows = observations(kept)
    clean = [r for r in rows if not r["large_move"]]
    pre = [r for r in rows if r["base_year"] + r["h"] < 2020]    # target year before the pandemic
    post = [r for r in rows if r["base_year"] + r["h"] >= 2020]
    res = {
        "study": "forecast-accuracy", "version": 1, "engine": engine, "as_of": as_of,
        "sample": {
            "universe": universe_size, "companies_with_filings": len(panels),
            "excluded_finance": len(panels) - len(kept),
            "companies_scored": len({r["cik"] for r in rows}),
            "origins": sum(len(p["origins"]) for p in kept),
            "origins_engine_errors": sum(p.get("engine_errors", 0) for p in kept),
            "observations": len(rows),
            "base_years": [min((r["base_year"] for r in rows), default=None),
                           max((r["base_year"] for r in rows), default=None)],
        },
        "accuracy": accuracy(rows),
        "coverage": coverage(rows),
        "bias_by_growth": bias_by_growth(rows),
        "margin": margin_accuracy(rows),
        "by_division": by_division(rows),
        "robustness": {
            "no_large_moves": {"n": len(clean), "accuracy": accuracy(clean), "coverage": coverage(clean)},
            "targets_before_2020": {"n": len(pre), "accuracy": accuracy(pre), "coverage": coverage(pre)},
            "targets_2020_on": {"n": len(post), "accuracy": accuracy(post), "coverage": coverage(post)},
        },
    }
    res["headline"] = headline(res)
    res["memo"] = memo(res)
    return res


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def headline(res: dict) -> dict:
    """Plain-language answer and verdicts, computed from the results so no number is typed by hand.
    Each hypothesis is called supported only when the evidence clears a clustered t of 2."""
    acc = {(a["method"], a["h"]): a for a in res["accuracy"]}
    cov = {c["h"]: c for c in res["coverage"]}
    m3, n3 = acc.get(("model", 3)), acc.get(("naive", 3))
    if not m3 or 3 not in cov:
        return {"lead": "Not enough data to score.", "sub": "", "findings": [], "kpis": []}
    miss = math.exp(m3["median_abs_error"]) - 1
    c1, c3, c5 = (cov.get(h, {}).get("coverage") for h in (1, 3, 5))
    lead = (f"Three years out, a forecast built from a company's own filings misses actual revenue by a median "
            f"{_pct(miss)}, and the model's 80% range contains the outcome {_pct(c3)} of the time.")
    skill, t = m3["skill_vs_naive"], m3["loss_diff_vs_naive"]["t"]
    h3 = acc.get(("hist3", 3))
    if t is not None and abs(t) < 2:
        sub = (f"The model's fading-growth forecast is about as accurate as assuming no change "
               f"({_pct(abs(skill))} {'less' if skill >= 0 else 'more'} error, t = {t:.1f}, not a real difference). ")
    else:
        sub = (f"The model's fading-growth forecast has {_pct(abs(skill))} {'less' if skill >= 0 else 'more'} error than "
               f"assuming no change, so the method {'helps' if skill >= 0 else 'does worse than doing nothing'}. ")
    if h3 and h3["loss_diff_vs_naive"]["t"] is not None and h3["loss_diff_vs_naive"]["t"] >= 2:
        sub += (f"Extrapolating a company's own three-year growth does clearly worse: {_pct(abs(h3['skill_vs_naive']))} "
                f"more error (t = {h3['loss_diff_vs_naive']['t']:.1f}). ")
    sub += (f"The range around the model is {'far ' if c3 < 0.6 else ''}narrower than the uncertainty it describes."
            if c3 < 0.8 else "The range around the model is about as wide as the uncertainty it describes, or wider.")

    findings = []
    g = res["bias_by_growth"]
    if g:
        top, bottom = g[-1]["model"], g[0]["model"]
        ok = top["mean"] is not None and top["t"] is not None and top["mean"] > 0 and top["t"] >= 2
        findings.append({"label": f"H1 {'supported' if ok else 'not supported'}",
                         "text": f"For the fastest growers (top tenth, median prior growth {_pct(g[-1]['g3_median'])}), "
                                 f"the model's three-year forecast averaged {_pct(math.exp(top['mean']) - 1)} too "
                                 f"{'high' if top['mean'] > 0 else 'low'} (t = {top['t']:.1f}); for the slowest tenth, "
                                 f"{_pct(abs(math.exp(bottom['mean']) - 1))} too {'high' if bottom['mean'] > 0 else 'low'}."})
    mg = next((m for m in res["margin"] if m["h"] == 3), None)
    if mg:
        t = mg["loss_diff_hist3_vs_naive"]["t"]
        ok = t is None or t >= -2
        findings.append({"label": f"H2 {'supported' if ok else 'not supported'}",
                         "text": f"Three years out, holding last year's operating margin missed by a median "
                                 f"{mg['median_abs_pp']['naive']:.1f} points against {mg['median_abs_pp']['hist3']:.1f} "
                                 f"for the three-year average (t = {t:.1f}, negative favors the average)."})
    below = all(c["coverage"] < 0.8 and c["p_vs_nominal"] is not None and c["p_vs_nominal"] < 0.05
                for c in res["coverage"])
    widening = c1 is not None and c5 is not None and c5 < c1 - 0.05   # a real fall, not noise
    findings.append({"label": f"H3 {'supported' if below and widening else 'partly supported' if below else 'not supported'}",
                     "text": f"The P10–P90 range held the outcome {_pct(c1)} of the time one year out and {_pct(c5)} five "
                             f"years out, against the 80% it implies. Misses fell {_pct(cov[3]['below'])} below the range "
                             f"and {_pct(cov[3]['above'])} above it three years out."})
    kpis = [{"value": _pct(miss), "label": "Median miss, model, 3 years out"},
            {"value": _pct(c3), "label": "Outcomes inside the 80% range, 3 years out"},
            {"value": f"{skill * 100:+.0f}%", "label": "Model accuracy vs no change, 3 years out"},
            {"value": f"{res['sample']['companies_scored']}", "label": "Companies scored"}]
    return {"lead": lead, "sub": sub, "findings": findings, "kpis": kpis}


def memo(res: dict) -> dict:
    """The one-page memo's practice points, worded from the results. Recommendations follow the evidence:
    a point is only made when the matching result clears the same t of 2 used for the verdicts."""
    acc = {(a["method"], a["h"]): a for a in res["accuracy"]}
    cov = {c["h"]: c for c in res["coverage"]}
    m3 = acc.get(("model", 3))
    if not m3 or 3 not in cov:
        return {"practice": [], "valuation_model": []}
    practice, changes = [], []
    c3 = cov[3]["coverage"]
    if c3 < 0.8 and cov[3]["p_vs_nominal"] is not None and cov[3]["p_vs_nominal"] < 0.05:
        practice.append({"title": "Widen the range.",
                         "text": f"A band meant to hold 80% of outcomes held {_pct(c3)}. Treat a P10–P90 from growth "
                                 f"noise alone as a floor on uncertainty, not an estimate of it."})
        changes.append("Calibrate the simulated growth spread to the error seen here, then re-test coverage "
                       "on origins the calibration did not use.")
    g = res["bias_by_growth"]
    if g and g[-1]["model"]["mean"] is not None and g[-1]["model"]["t"] is not None \
            and g[-1]["model"]["mean"] > 0 and g[-1]["model"]["t"] >= 2:
        practice.append({"title": "Fade high growth faster.",
                         "text": f"For companies growing a median {_pct(g[-1]['g3_median'])} a year, the forecast ran "
                                 f"{_pct(math.exp(g[-1]['model']['mean']) - 1)} high three years out. Recent growth is a "
                                 f"weak guide to the next three years."})
        changes.append("Test a shorter fade, or a starting growth rate shrunk toward the sector, against this set.")
    skill, t = m3["skill_vs_naive"], m3["loss_diff_vs_naive"]["t"]
    h3 = acc.get(("hist3", 3))
    if t is not None and t > -2:   # the model did not measurably beat no change
        worse = (f" Straight extrapolation of recent growth was {_pct(abs(h3['skill_vs_naive']))} worse "
                 f"(t = {h3['loss_diff_vs_naive']['t']:.1f})."
                 if h3 and h3["loss_diff_vs_naive"]["t"] is not None and h3["loss_diff_vs_naive"]["t"] >= 2 else "")
        practice.append({"title": "Beat no change first.",
                         "text": f"Three years out, the model was not measurably better than assuming revenue stays flat "
                                 f"({_pct(abs(skill))} {'less' if skill >= 0 else 'more'} error, t = {t:.1f}).{worse} "
                                 f"Argue any growth story against that baseline, not from it."})
        changes.append("Report the no-change case beside every DCF, with this study's error rates attached.")
    return {"practice": practice, "valuation_model": changes}
