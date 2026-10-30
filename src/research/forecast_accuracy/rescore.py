"""Study 1b: Study 1's forecasts scored again after the Valuation Model's fixes.

Same companies, same filing dates, same first-reported actuals, same scoring. Before is the model
Study 1 tested: the fading-growth path with a range from a +/-3 point triangular wobble in growth.
After is what the engine ships from 0.9.0: a base case that blends no change, the fade and the
sector's growth, and ranges taken from the spread of past misses, scaled by how volatile the
company's revenue has been (calibration.py).

The ranges are scored out of sample and point in time: each forecast from base year 2014 on is scored
with quantiles built only from errors whose actual had been filed by that forecast's own filing date
(a past fiscal year having ended is not enough; its 10-K may not be out yet), and the old band is scored on exactly the same
observations. The blend has no fitted weights, but it was chosen after looking at this data, so the
splits (before and after 2020, by sector, by prior growth) are the guard against having fit noise;
the next years' 10-Ks are the real out-of-sample test.
"""
from __future__ import annotations

import math
from bisect import insort
from collections import defaultdict
from statistics import median

from .calibration import _q, add_blend, known_quantiles, scale
from .metrics import (accuracy, bias_by_growth, by_division, clustered_mean, division, norm_p, observations,
                      winsorize)
from .methods import HORIZONS
from .study import EXCLUDED_DIVISIONS, add_sector_forecasts

LEVELS = (0.8, 0.9, 0.95)
FIRST_TEST_YEAR = 2014
MIN_CALIBRATION = 200
VOL_GROUPS = ("steady", "middle", "volatile")


def range_hits(panels: list[dict], center: str = "blend", levels=LEVELS, first_year: int = FIRST_TEST_YEAR,
               min_calibration: int = MIN_CALIBRATION) -> list[dict]:
    """One row per scored observation from `first_year` on: whether the actual fell inside the calibrated
    range at each level, inside the old P10-P90 band, and how far each range reached below and above its
    forecast. Each observation's quantiles come only from errors whose actual had been filed on or before
    its own origin date (known_errors), so the range is what the model could have been calibrated to that day."""
    obs: dict[int, list[dict]] = {h: [] for h in HORIZONS}
    for p in panels:
        if division(p.get("sic")) in EXCLUDED_DIVISIONS:
            continue
        for o in p["origins"]:
            if o["n_history"] < 3:
                continue
            f, s, rev = o["revenue"].get(center) or {}, scale(o["history"]), o["revenue"]
            for h in HORIZONS:
                a = o["actual"].get(h)
                if a and a > 0 and f.get(h) and f[h] > 0:
                    obs[h].append({"cik": p["cik"], "h": h, "year": int(o["base_end"][:4]), "s": s,
                                   "origin": o["origin"], "known": o["actual_origin"][h],
                                   "e": math.log(a / f[h]), "z": math.log(a / f[h]) / s, "a": a,
                                   "old": (rev["model_p10"][h], rev["model"][h], rev["model_p90"][h])})
    out = []
    for h, rows in obs.items():
        tests = [r for r in rows if r["year"] >= first_year]
        for r, (n, q) in zip(tests, known_quantiles(rows, tests, levels)):
            if n < min_calibration:
                continue
            lo_old, mid_old, hi_old = r["old"]
            out.append({
                "cik": r["cik"], "h": h, "year": r["year"], "origin": r["origin"], "scale": r["s"], "n_calibration": n,
                "hit": {lvl: lo * r["s"] <= r["e"] <= hi * r["s"] for lvl, (lo, hi) in q.items()},
                "reach": {lvl: (1 - math.exp(lo * r["s"]), math.exp(hi * r["s"]) - 1) for lvl, (lo, hi) in q.items()},
                "old_hit": lo_old <= r["a"] <= hi_old,
                "old_reach": (1 - lo_old / mid_old, hi_old / mid_old - 1),
            })
    return out


def _share(rows: list[dict], key, nominal: float | None = None) -> dict:
    """Share of rows where key(row) is true, with a company-clustered standard error."""
    c = clustered_mean([1.0 if key(r) else 0.0 for r in rows], [r["cik"] for r in rows])
    z = (c["mean"] - nominal) / c["se"] if nominal is not None and c["se"] else None
    return {"n": c["n"], "share": c["mean"], "se": c["se"], "z_vs_nominal": z,
            "p_vs_nominal": norm_p(z) if z is not None else None}


def coverage_before_after(hits: list[dict], levels=LEVELS) -> list[dict]:
    """Per horizon: the old band against 80%, each calibrated range against its own level, and how wide each is."""
    out = []
    for h in HORIZONS:
        rs = [r for r in hits if r["h"] == h]
        if not rs:
            continue
        row = {"h": h, "n": len(rs), "companies": len({r["cik"] for r in rs}),
               "before": {**_share(rs, lambda r: r["old_hit"], 0.8),
                          "below": median(r["old_reach"][0] for r in rs), "above": median(r["old_reach"][1] for r in rs)},
               "after": {}}
        for lvl in levels:
            row["after"][str(round(lvl * 100))] = {
                **_share(rs, lambda r, lvl=lvl: r["hit"][lvl], lvl),
                "below": median(r["reach"][lvl][0] for r in rs), "above": median(r["reach"][lvl][1] for r in rs)}
        out.append(row)
    return out


def coverage_by(hits: list[dict], group, h: int = 3, levels=(0.8, 0.9)) -> list[dict]:
    """Coverage at one horizon split by group(row): the range should hold its level in every slice,
    not just on average."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in hits:
        if r["h"] == h:
            groups[group(r)].append(r)
    return [{"group": g, "n": len(rs), "before": _share(rs, lambda r: r["old_hit"])["share"],
             **{str(round(lvl * 100)): _share(rs, lambda r, lvl=lvl: r["hit"][lvl])["share"] for lvl in levels}}
            for g, rs in groups.items()]


def _vol_group(hits: list[dict], h: int = 3):
    """Terciles of the company scale at horizon h: steady, middle, volatile."""
    s = sorted(r["scale"] for r in hits if r["h"] == h)
    cuts = (_q(s, 1 / 3), _q(s, 2 / 3)) if s else (0, 0)
    return lambda r: VOL_GROUPS[(r["scale"] > cuts[0]) + (r["scale"] > cuts[1])]


def paired(rows: list[dict], a: str, b: str) -> list[dict]:
    """Per horizon: mean |error| of a minus b on the same observations, clustered by company (< 0 = a better)."""
    out = []
    for h in HORIZONS:
        rs = [r for r in rows if r["h"] == h and a in r["err"] and b in r["err"]]
        if not rs:
            continue
        ea = [abs(x) for x in winsorize([r["err"][a] for r in rs])]
        eb = [abs(x) for x in winsorize([r["err"][b] for r in rs])]
        d = clustered_mean([x - y for x, y in zip(ea, eb)], [r["cik"] for r in rs])
        out.append({"h": h, "n": len(rs), "gain": 1 - sum(ea) / sum(eb), "t": d["t"], "p": d["p"]})
    return out


def run(panels: list[dict], *, engine: str, as_of: str, universe_size: int,
        min_calibration: int = MIN_CALIBRATION) -> dict:
    kept = [p for p in panels if division(p.get("sic")) not in EXCLUDED_DIVISIONS]
    add_sector_forecasts(kept)
    add_blend(kept)
    rows = observations(kept)
    hits = range_hits(kept, min_calibration=min_calibration)
    methods = ("naive", "model", "blend")
    split = {"targets_before_2020": [r for r in rows if r["base_year"] + r["h"] < 2020],
             "targets_2020_on": [r for r in rows if r["base_year"] + r["h"] >= 2020]}
    res = {
        "study": "forecast-accuracy-rescore", "version": 1, "engine": engine, "as_of": as_of,
        "sample": {
            "universe": universe_size, "excluded_finance": len(panels) - len(kept),
            "companies_scored": len({r["cik"] for r in rows}), "observations": len(rows),
            "origins_engine_errors": sum(p.get("engine_errors", 0) for p in kept),
            "base_years": [min((r["base_year"] for r in rows), default=None),
                           max((r["base_year"] for r in rows), default=None)],
            "range_test": {"first_base_year": FIRST_TEST_YEAR, "min_calibration": min_calibration,
                           "observations": len(hits), "companies": len({r["cik"] for r in hits})},
        },
        "accuracy": accuracy(rows, methods),
        "blend_vs_model": paired(rows, "blend", "model"),
        "bias_by_growth": bias_by_growth(rows, methods=("model", "blend")),
        "by_division": by_division(rows, methods=("model", "blend")),
        "splits": {k: {"n": len(v), "accuracy": accuracy(v, methods)} for k, v in split.items()},
        "coverage": coverage_before_after(hits),
        "coverage_by_year": sorted(coverage_by(hits, lambda r: str(r["year"])), key=lambda g: g["group"]),
        "coverage_by_volatility": sorted(coverage_by(hits, _vol_group(hits)), key=lambda g: VOL_GROUPS.index(g["group"])),
    }
    res["headline"] = headline(res)
    res["memo"] = memo(res)
    return res


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def headline(res: dict) -> dict:
    """The before-and-after answer in words, computed from the results. A gain is called real only at |t| >= 2."""
    acc = {(a["method"], a["h"]): a for a in res["accuracy"]}
    cov = {c["h"]: c for c in res["coverage"]}
    b3, m3 = acc.get(("blend", 3)), acc.get(("model", 3))
    if not b3 or not m3 or 3 not in cov:
        return {"lead": "Not enough data to score.", "sub": "", "kpis": []}
    miss_b, miss_m = (math.exp(x["median_abs_error"]) - 1 for x in (b3, m3))
    sk, t = b3["skill_vs_naive"], b3["loss_diff_vs_naive"]["t"]
    real = t is not None and t <= -2
    before, after80, after90 = cov[3]["before"]["share"], cov[3]["after"]["80"]["share"], cov[3]["after"]["90"]["share"]
    lead = (f"After the fixes, a range built to hold 80% of outcomes held {_pct(after80)} of outcomes it had not seen "
            f"three years out, up from {_pct(before)}; the 90% range held {_pct(after90)}.")
    sub = (f"The new base case misses three-year revenue by a median {_pct(miss_b)} against {_pct(miss_m)} for the old one, and "
           + (f"is {_pct(sk)} more accurate than assuming no change (t = {abs(t):.1f})."
              if real and sk > 0 else
              f"is not measurably better than assuming no change ({_pct(abs(sk))} {'less' if sk >= 0 else 'more'} error, "
              f"t = {abs(t):.1f})."))
    kpis = [{"value": f"{_pct(before)} → {_pct(after80)}", "label": "Outcomes inside the 80% range, 3 years out"},
            {"value": _pct(after90), "label": "Outcomes inside the 90% range, 3 years out"},
            {"value": f"{sk * 100:+.0f}%", "label": "New base case accuracy vs no change, 3 years out"},
            {"value": f"{res['sample']['companies_scored']}", "label": "Companies scored"}]
    return {"lead": lead, "sub": sub, "kpis": kpis}


def _off(mean_log: float) -> str:
    x = math.exp(mean_log) - 1
    return f"{_pct(abs(x))} {'high' if x >= 0 else 'low'}"


def memo(res: dict) -> dict:
    """The one-page memo's findings and practice points, worded from the results (no typed numbers)."""
    cov = {c["h"]: c for c in res["coverage"]}
    acc = {(a["method"], a["h"]): a for a in res["accuracy"]}
    gain = {g["h"]: g for g in res["blend_vs_model"]}
    if 3 not in cov or ("blend", 3) not in acc:
        return {"findings": [], "practice": []}
    findings, practice = [], []
    hs = [h for h in (1, 3, 5) if h in cov]
    findings.append({"label": "Ranges",
                     "text": "The old P10–P90 band held " + ", ".join(f"{_pct(cov[h]['before']['share'])} ({h} yr)" for h in hs)
                             + " of outcomes; the calibrated 80% range held "
                             + ", ".join(f"{_pct(cov[h]['after']['80']['share'])} ({h} yr)" for h in hs)
                             + f", each scored only on forecasts its calibration had not seen "
                               f"({res['sample']['range_test']['observations']:,} forecasts, "
                               f"{res['sample']['range_test']['companies']} companies)."})
    yr = [g["80"] for g in res.get("coverage_by_year", []) if g["n"] >= 30]
    vol = res.get("coverage_by_volatility", [])
    if yr and vol:
        findings.append({"label": "Held in every slice?",
                         "text": f"Three years out, the 80% range held {_pct(min(yr))}–{_pct(max(yr))} across base years and "
                                 + ", ".join(f"{_pct(g['80'])} for {g['group']}" for g in vol) + " companies by revenue volatility."})
    g3 = gain.get(3)
    if g3:
        b3, sk, t = acc[("blend", 3)], acc[("blend", 3)]["skill_vs_naive"], acc[("blend", 3)]["loss_diff_vs_naive"]["t"]
        findings.append({"label": "Base case",
                         "text": f"Three years out the blended base case had {_pct(abs(g3['gain']))} "
                                 f"{'less' if g3['gain'] >= 0 else 'more'} error than the old fade (t = {abs(g3['t']):.1f}) and "
                                 f"{_pct(abs(sk))} {'less' if sk >= 0 else 'more'} than assuming no change (t = {abs(t):.1f}); "
                                 f"its median miss was {_pct(math.exp(b3['median_abs_error']) - 1)}."})
    bg = res.get("bias_by_growth") or []
    if bg:
        top = bg[-1]
        findings.append({"label": "Fast growers",
                         "text": f"For the fastest-growing tenth (median prior growth {_pct(top['g3_median'])}), the old forecast ran "
                                 f"{_off(top['model']['mean'])} three years out (t = {top['model']['t']:.1f}); "
                                 f"the blend ran {_off(top['blend']['mean'])} (t = {top['blend']['t']:.1f})."})
    a80 = cov[3]["after"]["80"]
    if a80["p_vs_nominal"] is not None and a80["p_vs_nominal"] >= 0.05:
        practice.append({"title": "Read the 80% range at face value.",
                         "text": f"It held {_pct(a80['share'])} three years out, not measurably different from 80%. It is wide: "
                                 f"a median {_pct(a80['below'])} below and {_pct(a80['above'])} above the base case."})
    else:
        practice.append({"title": "Adjust the 80% range.",
                         "text": f"It held {_pct(a80['share'])} three years out, measurably "
                                 f"{'more' if a80['share'] > 0.8 else 'less'} than 80% (z = {a80['z_vs_nominal']:.1f})."})
    if gain and all(g["t"] is not None and g["t"] <= -2 for g in gain.values()):
        practice.append({"title": "Start from the blend, not recent growth.",
                         "text": f"Averaging no change, the faded trend and the sector beat the fade at every horizon "
                                 f"from 1 to {max(gain)} years. Argue for departing from it with company-specific evidence."})
    practice.append({"title": "Treat this as in-sample until new 10-Ks arrive.",
                     "text": "The blend was chosen after seeing this data. The ranges were tested out of sample, but the "
                             "forecasts filed after this study are the real test."})
    return {"findings": findings, "practice": practice}
