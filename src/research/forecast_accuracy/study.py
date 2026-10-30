"""The whole study from company panels to the published results document.

Five revenue forecasts are compared on the same observations: no change, the company's own three-year
growth, its sector's median growth, the Valuation Model's fading-growth path, and a blend (the geometric
mean of no change, the fade and the sector). Two ways of drawing a range around a forecast are compared
too (ranges.py). Everything is point in time: each forecast, sector median and range uses only filings
public on the day it is made."""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta
from statistics import median

from . import ranges
from .calibration import add_blend
from .methods import sector_forecasts
from .metrics import (accuracy, bias_by_growth, by_division, coverage, division, margin_accuracy,
                      observations)

MIN_SECTOR_PEERS = 5
EXCLUDED_DIVISIONS = ranges.EXCLUDED_DIVISIONS
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


METHODS = ("naive", "hist3", "sector", "model", "blend")
NAMES = {"naive": "no change", "hist3": "the company's own three-year growth", "sector": "the sector's growth",
         "model": "faded growth", "blend": "the blend"}


def run(panels: list[dict], *, engine: str, as_of: str, universe_size: int,
        min_calibration: int = ranges.MIN_CALIBRATION) -> dict:
    kept = [p for p in panels if division(p.get("sic")) not in EXCLUDED_DIVISIONS]
    add_sector_forecasts(kept)
    add_blend(kept)
    rows = observations(kept)
    hits = ranges.range_hits(kept, min_calibration=min_calibration)
    clean = [r for r in rows if not r["large_move"]]
    pre = [r for r in rows if r["base_year"] + r["h"] < 2020]    # target year before the pandemic
    post = [r for r in rows if r["base_year"] + r["h"] >= 2020]
    res = {
        "study": "forecast-accuracy", "version": 2, "engine": engine, "as_of": as_of,
        "sample": {
            "universe": universe_size, "companies_with_filings": len(panels),
            "excluded_finance": len(panels) - len(kept),
            "companies_scored": len({r["cik"] for r in rows}),
            "origins": sum(len(p["origins"]) for p in kept),
            "origins_engine_errors": sum(p.get("engine_errors", 0) for p in kept),
            "observations": len(rows),
            "base_years": [min((r["base_year"] for r in rows), default=None),
                           max((r["base_year"] for r in rows), default=None)],
            "range_test": {"first_base_year": ranges.FIRST_TEST_YEAR, "min_calibration": min_calibration,
                           "observations": len(hits), "companies": len({r["cik"] for r in hits})},
        },
        "accuracy": accuracy(rows, METHODS),
        "blend_vs_model": ranges.paired(rows, "blend", "model"),
        "coverage": coverage(rows),
        "ranges": ranges.coverage_by_horizon(hits),
        "ranges_by_year": sorted(ranges.coverage_by(hits, lambda r: str(r["year"])), key=lambda g: g["group"]),
        "ranges_by_volatility": sorted(ranges.coverage_by(hits, ranges._vol_group(hits)),
                                       key=lambda g: ranges.VOL_GROUPS.index(g["group"])),
        "bias_by_growth": bias_by_growth(rows, methods=("model", "hist3", "blend")),
        "margin": margin_accuracy(rows),
        "by_division": by_division(rows, methods=("model", "hist3", "blend")),
        "robustness": {
            "no_large_moves": {"n": len(clean), "accuracy": accuracy(clean, METHODS), "coverage": coverage(clean)},
            "targets_before_2020": {"n": len(pre), "accuracy": accuracy(pre, METHODS), "coverage": coverage(pre)},
            "targets_2020_on": {"n": len(post), "accuracy": accuracy(post, METHODS), "coverage": coverage(post)},
        },
    }
    res["headline"] = headline(res)
    res["memo"] = memo(res)
    return res


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def _off(mean_log: float) -> str:
    x = math.exp(mean_log) - 1
    return f"{_pct(abs(x))} too {'high' if x >= 0 else 'low'}"


def _vs(a: dict) -> str:
    """'7% less error (t = 4.7)' against no change, flagged when it doesn't clear t = 2."""
    skill, t = a["skill_vs_naive"], a["loss_diff_vs_naive"]["t"]
    s = f"{_pct(abs(skill))} {'less' if skill >= 0 else 'more'} error"
    if t is None:
        return s
    return f"{s} (t = {abs(t):.1f}{', not a real difference' if abs(t) < 2 else ''})"


def headline(res: dict) -> dict:
    """Plain-language answer and verdicts, computed from the results so no number is typed by hand.
    A difference is called real only when it clears a clustered t of 2."""
    acc = {(a["method"], a["h"]): a for a in res["accuracy"]}
    cov = {c["h"]: c for c in res["coverage"]}
    rng = {c["h"]: c for c in res["ranges"]}
    b3, m3, h3 = acc.get(("blend", 3)), acc.get(("model", 3)), acc.get(("hist3", 3))
    if not b3 or not m3 or 3 not in cov or 3 not in rng:
        return {"lead": "Not enough data to score.", "sub": "", "findings": [], "kpis": []}
    miss = math.exp(b3["median_abs_error"]) - 1
    c80, c90 = rng[3]["calibrated"]["80"]["share"], rng[3]["calibrated"]["90"]["share"]
    sim = rng[3]["simulated"]["share"]
    best = max((a for a in res["accuracy"] if a["h"] == 3 and a["method"] != "naive"), key=lambda a: a["skill_vs_naive"])
    lead = (f"Three years out, a blend of no change, faded growth and the sector's growth misses actual revenue by a "
            f"median {_pct(miss)}, and a range built from past misses held the outcome {_pct(c80)} of the time at 80% "
            f"and {_pct(c90)} at 90%.")
    sub = (f"Against assuming no change, the blend had {_vs(b3)}; fading the company's own growth, a common DCF "
           f"starting point, had {_vs(m3)}")
    if h3:
        sub += f"; extrapolating that growth straight had {_vs(h3)}"
    sub += "."
    if best["method"] != "blend":
        sub += f" The most accurate forecast tested was {NAMES[best['method']]}, with {_vs(best)}."
    sub += f" A range from a ±3-point wobble in growth held only {_pct(sim)} against the 80% it implies."

    findings = []
    g = res["bias_by_growth"]
    if g:
        top, bottom = g[-1]["model"], g[0]["model"]
        ok = top["mean"] is not None and top["t"] is not None and top["mean"] > 0 and top["t"] >= 2
        text = (f"For the fastest growers (top tenth, median prior growth {_pct(g[-1]['g3_median'])}), the faded-growth "
                f"forecast ran {_off(top['mean'])} three years out (t = {top['t']:.1f}); for the slowest tenth, "
                f"{_off(bottom['mean'])}.")
        if g[-1].get("blend") and g[-1]["blend"]["t"] is not None:
            text += f" The blend ran {_off(g[-1]['blend']['mean'])} for the fastest growers (t = {g[-1]['blend']['t']:.1f})."
        findings.append({"label": f"H1 {'supported' if ok else 'not supported'}", "text": text})
    mg = next((m for m in res["margin"] if m["h"] == 3), None)
    if mg:
        t = mg["loss_diff_hist3_vs_naive"]["t"]
        ok = t is None or t >= -2
        findings.append({"label": f"H2 {'supported' if ok else 'not supported'}",
                         "text": f"Three years out, holding last year's operating margin missed by a median "
                                 f"{mg['median_abs_pp']['naive']:.1f} points against {mg['median_abs_pp']['hist3']:.1f} "
                                 f"for the three-year average (t = {t:.1f}, negative favors the average)."})
    c1, c5 = (cov.get(h, {}).get("coverage") for h in (1, 5))
    below = all(c["coverage"] < 0.8 and c["p_vs_nominal"] is not None and c["p_vs_nominal"] < 0.05
                for c in res["coverage"])
    widening = c1 is not None and c5 is not None and c5 < c1 - 0.05   # a real fall, not noise
    findings.append({"label": f"H3 {'supported' if below and widening else 'partly supported' if below else 'not supported'}",
                     "text": f"The simulated P10–P90 range held the outcome {_pct(c1)} of the time one year out and "
                             f"{_pct(c5)} five years out, against the 80% it implies. Misses fell {_pct(cov[3]['below'])} "
                             f"below the range and {_pct(cov[3]['above'])} above it three years out."})
    kpis = [{"value": _pct(miss), "label": "Median miss, blended forecast, 3 years out"},
            {"value": _pct(c80), "label": "Outcomes inside the calibrated 80% range, 3 years out"},
            {"value": f"{b3['skill_vs_naive'] * 100:+.0f}%", "label": "Blended forecast vs no change, 3 years out"},
            {"value": f"{res['sample']['companies_scored']}", "label": "Companies scored"}]
    return {"lead": lead, "sub": sub, "findings": findings, "kpis": kpis}


def memo(res: dict) -> dict:
    """The one-page memo's practice points, worded from the results. A point is only made when the matching
    result clears the same evidence bar used for the verdicts."""
    acc = {(a["method"], a["h"]): a for a in res["accuracy"]}
    rng = {c["h"]: c for c in res["ranges"]}
    gain = {g["h"]: g for g in res["blend_vs_model"]}
    b3, m3 = acc.get(("blend", 3)), acc.get(("model", 3))
    if not b3 or not m3 or 3 not in rng:
        return {"practice": [], "valuation_model": []}
    practice, model = [], []
    sim, a80 = rng[3]["simulated"], rng[3]["calibrated"]["80"]
    if sim["p_vs_nominal"] is not None and sim["p_vs_nominal"] < 0.05 and sim["share"] < 0.8:
        practice.append({"title": "Draw ranges from past misses, not from a growth wobble.",
                         "text": f"A ±3-point band in growth held {_pct(sim['share'])} of outcomes three years out. Quantiles "
                                 f"of past forecast errors, scaled to the company's volatility, held {_pct(a80['share'])} "
                                 f"at 80%, reaching a median {_pct(a80['below'])} below and {_pct(a80['above'])} above the "
                                 f"forecast. Honest ranges are wide."})
        model.append("Revenue ranges in the DCF simulation are drawn from this study's calibrated error table.")
    g = res["bias_by_growth"]
    if g and g[-1]["model"]["mean"] is not None and g[-1]["model"]["t"] is not None \
            and g[-1]["model"]["mean"] > 0 and g[-1]["model"]["t"] >= 2:
        practice.append({"title": "Don't trust recent high growth.",
                         "text": f"For companies growing a median {_pct(g[-1]['g3_median'])} a year, a faded-growth forecast ran "
                                 f"{_off(g[-1]['model']['mean'])} three years out. Pull the starting rate toward no change "
                                 f"and the sector."})
    bt, mt = b3["loss_diff_vs_naive"]["t"], m3["loss_diff_vs_naive"]["t"]
    if gain and all(x["t"] is not None and x["t"] <= -2 for x in gain.values()) and bt is not None and bt <= -2:
        practice.append({"title": "Start from the blend.",
                         "text": f"The geometric mean of no change, the faded trend and the sector beat the fade alone at every "
                                 f"horizon from 1 to {max(gain)} years, and beat no change by {_pct(b3['skill_vs_naive'])} "
                                 f"three years out (t = {abs(bt):.1f}). Depart from it only with company-specific evidence."})
        model.append("The default DCF's base case for years 1–5 is the blend.")
    if mt is not None and mt > -2:
        practice.append({"title": "Beat no change first.",
                         "text": f"Three years out, fading the company's own growth was not measurably better than assuming "
                                 f"revenue stays flat ({_vs(m3)}). Argue any growth story against "
                                 f"that baseline."})
        model.append("Every DCF shows the value with revenue held flat beside it.")
    return {"practice": practice, "valuation_model": model}
