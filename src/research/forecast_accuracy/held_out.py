"""The held-out test: Study 01's methods, unchanged, scored on companies the study never looked at.

The plan was committed before the run (docs/preregistration/forecast-accuracy-held-out.md). Three primary
results three years out decide it: the blend beats no change (P1) and faded growth (P2) with t >= 2, and the
calibrated 80% range holds 75-85% of outcomes (P3). The ranges are calibrated on Study 01's companies only,
with errors known by each held-out forecast's filing date, so they are held out by company and by time.

Two baselines are shown beside the blend: shrinkage (half the three-year growth, held flat) and a fixed band
of the same median width as the calibrated 80% range. Drift and an unscaled range are in the notebook."""
from __future__ import annotations

import math
from statistics import median

from . import ranges
from .calibration import add_blend
from .methods import HORIZONS
from .metrics import accuracy, division, observations
from .study import EXCLUDED_DIVISIONS, NAMES, add_sector_forecasts

METHODS = ("naive", "hist3", "sector", "model", "blend", "shrink", "drift")
SHRINK = 0.5
PRIMARY_H = 3
P3_BAND = (0.75, 0.85)
T_BAR = 2.0
NAMES = {**NAMES, "shrink": "half of recent growth", "drift": "the company's median yearly growth"}


def add_baselines(panels: list[dict]) -> None:
    """shrink: R0 * (1 + 0.5 * g3)^h. drift: R0 * exp(h * median yearly log growth over the history)."""
    for p in panels:
        for o in p["origins"]:
            r0, g3, hist = o["r0"], o["g3"], o["history"]
            if g3 is not None:
                o["revenue"]["shrink"] = {h: r0 * (1 + SHRINK * g3) ** h for h in HORIZONS}
            g = [math.log(b / a) for a, b in zip(hist, hist[1:]) if a > 0 and b > 0]
            if g:
                mu = median(g)
                o["revenue"]["drift"] = {h: r0 * math.exp(mu * h) for h in HORIZONS}


def holm(pvals: list[float | None]) -> list[float | None]:
    """Holm step-down adjusted p-values (None stays None)."""
    idx = sorted((i for i, p in enumerate(pvals) if p is not None), key=lambda i: pvals[i])
    m, out, running = len(idx), [None] * len(pvals), 0.0
    for k, i in enumerate(idx):
        running = max(running, min(1.0, (m - k) * pvals[i]))
        out[i] = running
    return out


def paired(rows: list[dict], a: str, b: str) -> list[dict]:
    """ranges.paired plus each horizon's Holm-adjusted p across the horizons."""
    out = ranges.paired(rows, a, b)
    for r, adj in zip(out, holm([r["p"] for r in out])):
        r["p_holm"] = adj
    return out


def range_table(hits: list[dict]) -> list[dict]:
    """Per horizon: calibrated 80/90% (scaled), unscaled 80/90%, and the fixed band at the calibrated 80% range's
    median half-width (in log terms, around the blend)."""
    out = []
    for h in HORIZONS:
        rs = [r for r in hits if r["h"] == h]
        if not rs:
            continue
        w = median(r["half"][0.8] for r in rs)
        row = {"h": h, "n": len(rs), "companies": len({r["cik"] for r in rs}), "fixed_half_width": w,
               "fixed": ranges._share(rs, lambda r, w=w: abs(r["e"]) <= w, 0.8)}
        for lvl in (0.8, 0.9):
            k = str(round(lvl * 100))
            row[f"calibrated_{k}"] = ranges._share(rs, lambda r, lvl=lvl: r["hit"][lvl], lvl)
            row[f"unscaled_{k}"] = ranges._share(rs, lambda r, lvl=lvl: r.get("hit_unscaled", {}).get(lvl, False), lvl)
        out.append(row)
    return out


def primary(acc: list[dict], vs_fade: list[dict], rng: list[dict]) -> list[dict]:
    a = next((x for x in acc if x["method"] == "blend" and x["h"] == PRIMARY_H), None)
    f = next((x for x in vs_fade if x["h"] == PRIMARY_H), None)
    c = next((x for x in rng if x["h"] == PRIMARY_H), None)
    out = []
    if a:
        t = a["loss_diff_vs_naive"]["t"]
        out.append({"id": "P1", "test": "Blend vs no change, 3 years out", "gain": a["skill_vs_naive"], "t": t,
                    "passed": bool(t is not None and a["skill_vs_naive"] > 0 and t <= -T_BAR)})
    if f:
        out.append({"id": "P2", "test": "Blend vs faded growth, 3 years out", "gain": f["gain"], "t": f["t"],
                    "passed": bool(f["t"] is not None and f["gain"] > 0 and f["t"] <= -T_BAR)})
    if c:
        s = c["calibrated_80"]["share"]
        out.append({"id": "P3", "test": "Outcomes inside the calibrated 80% range, 3 years out", "share": s,
                    "se": c["calibrated_80"]["se"], "passed": bool(P3_BAND[0] <= s <= P3_BAND[1])})
    return out


def run(held: list[dict], calibration: list[dict], *, engine: str, as_of: str, universe_size: int,
        preregistration: str, min_calibration: int = ranges.MIN_CALIBRATION) -> dict:
    """held: panels of the held-out companies. calibration: Study 01's panels (the ranges' only source)."""
    kept = [p for p in held if division(p.get("sic")) not in EXCLUDED_DIVISIONS]
    cal = [p for p in calibration if division(p.get("sic")) not in EXCLUDED_DIVISIONS]
    for ps in (kept, cal):
        add_sector_forecasts(ps)
        add_blend(ps)
    add_baselines(kept)
    rows = observations(kept)
    acc = accuracy(rows, METHODS)
    for m in METHODS[1:]:     # Holm across horizons for each method's test against no change
        mine = [a for a in acc if a["method"] == m]
        for a, adj in zip(mine, holm([a["loss_diff_vs_naive"]["p"] for a in mine])):
            a["p_holm"] = adj
    vs_fade = paired(rows, "blend", "model")
    hits = ranges.range_hits(kept, min_calibration=min_calibration, calibration=cal)
    rng = range_table(hits)
    prim = primary(acc, vs_fade, rng)
    res = {
        "study": "forecast-accuracy-held-out", "version": 1, "engine": engine, "as_of": as_of,
        "preregistration": preregistration,
        "sample": {
            "universe": universe_size, "companies_with_filings": len(held), "excluded_finance": len(held) - len(kept),
            "companies_scored": len({r["cik"] for r in rows}), "observations": len(rows),
            "origins": sum(len(p["origins"]) for p in kept),
            "base_years": [min((r["base_year"] for r in rows), default=None),
                           max((r["base_year"] for r in rows), default=None)],
            "calibration_companies": len(cal),
            "range_test": {"first_base_year": ranges.FIRST_TEST_YEAR, "min_calibration": min_calibration,
                           "observations": len(hits), "companies": len({r["cik"] for r in hits})},
        },
        "primary": prim,
        "confirms": bool(len(prim) == 3 and all(p["passed"] for p in prim)),
        "accuracy": acc,
        "blend_vs_model": vs_fade,
        "blend_vs_shrink": paired(rows, "blend", "shrink"),
        "ranges": rng,
        "ranges_by_volatility": sorted(ranges.coverage_by(hits, ranges._vol_group(hits)),
                                       key=lambda g: ranges.VOL_GROUPS.index(g["group"])),
    }
    res["headline"] = headline(res)
    return res


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def _diff(gain: float, t: float | None) -> str:
    s = f"{_pct(abs(gain))} {'less' if gain >= 0 else 'more'} error"
    return s if t is None else f"{s} (t = {abs(t):.1f})"


def headline(res: dict) -> dict:
    """The held-out result in words, computed from the numbers."""
    p = {x["id"]: x for x in res["primary"]}
    if len(p) < 3:
        return {"lead": "Not enough held-out data to score.", "results": []}
    n = res["sample"]["companies_scored"]
    lead = (f"On {n} smaller companies the study had never looked at, the blend had {_diff(p['P1']['gain'], p['P1']['t'])} "
            f"than assuming no change three years out and {_diff(p['P2']['gain'], p['P2']['t'])} than faded growth, and "
            f"the calibrated 80% range held {_pct(p['P3']['share'])} of outcomes. "
            + ("All three tests set in advance passed." if res["confirms"] else
               "Not every test set in advance passed: " + ", ".join(x["id"] for x in res["primary"] if not x["passed"])
               + " failed."))
    acc = {(a["method"], a["h"]): a for a in res["accuracy"]}
    shrink = next((x for x in res["blend_vs_shrink"] if x["h"] == PRIMARY_H), None)
    r3 = next((x for x in res["ranges"] if x["h"] == PRIMARY_H), None)
    notes = []
    if shrink:
        notes.append(f"Against half of recent growth held flat, the blend had {_diff(shrink['gain'], shrink['t'])}.")
    if r3:
        notes.append(f"A fixed band of the same median width held {_pct(r3['fixed']['share'])}, against "
                     f"{_pct(r3['calibrated_80']['share'])} for the calibrated range.")
    return {"lead": lead, "notes": notes,
            "kpis": [{"value": f"{p['P1']['gain'] * 100:+.0f}%", "label": "Blend vs no change, held out, 3 years out"},
                     {"value": _pct(p["P3"]["share"]), "label": "Inside the 80% range, held out, 3 years out"},
                     {"value": f"{n}", "label": "Held-out companies scored"}]}
