"""Calibrated revenue ranges: quantiles of the model's past misses, for the Valuation Model.

The model's range used to come from a +/-3% triangular wobble in growth and held about 14% of
outcomes. Here the range is the spread of what actually happened: the log error of the model's
forecast (ln actual / forecast) at each horizon, divided by a company scale so steady companies
get narrow ranges and volatile ones wide ranges. Scale = the standard deviation of the company's
yearly log revenue growth over its history, plus SCALE_FLOOR.

How often the ranges hold out of sample, scored point in time (each forecast against quantiles of the
errors whose actuals had been filed by its own filing date), is in the table's `tested` field and in Study 1 (ranges.py).
"""
from __future__ import annotations

import math
from bisect import insort
from collections import defaultdict
from statistics import median, pstdev

from .methods import HORIZONS
from .metrics import division

SCALE_FLOOR = 0.10            # added to volatility, so a company with a smooth history still gets a range
DEFAULT_VOL = 0.10            # when the history is too short to measure
GRID = [round(0.005 * i, 3) for i in range(1, 200)]   # 0.5% steps, so P2.5, P5, P10 ... P97.5 are exact


def add_blend(panels: list[dict]) -> None:
    """The blended forecast: the geometric mean of no change, the model's fade and the sector's growth
    (the model when there's no sector forecast). Study 1 scores it against no change, the fade and the other forecasts.
    Panels must already carry sector forecasts (study.add_sector_forecasts)."""
    for p in panels:
        for o in p["origins"]:
            fc, r0 = o["revenue"], o["r0"]
            model, sector = fc.get("model") or {}, fc.get("sector") or fc.get("model") or {}
            o["revenue"]["blend"] = {h: (r0 * model[h] * sector[h]) ** (1 / 3) for h in HORIZONS
                                     if model.get(h) and sector.get(h)}


def sector_growth(panels: list[dict], min_peers: int = 5) -> dict:
    """Median three-year revenue CAGR by SIC division and base calendar year, for the blend's sector leg."""
    pool: dict[tuple, list[float]] = defaultdict(list)
    for p in panels:
        d = division(p.get("sic"))
        for o in p["origins"]:
            if d and d != "Finance" and o["g3"] is not None:
                pool[(d, int(o["base_end"][:4]))].append(o["g3"])
    out: dict[str, dict] = defaultdict(dict)
    for (d, y), gs in sorted(pool.items()):
        if len(gs) >= min_peers:
            out[d][str(y)] = {"median_cagr3": round(median(gs), 5), "n": len(gs)}
    return dict(out)


def revenue_vol(history: list[float]) -> float:
    """Standard deviation of yearly log revenue growth; DEFAULT_VOL with fewer than two changes."""
    g = [math.log(b / a) for a, b in zip(history, history[1:]) if a > 0 and b > 0]
    return pstdev(g) if len(g) >= 2 else DEFAULT_VOL


def scale(history: list[float]) -> float:
    return revenue_vol(history) + SCALE_FLOOR


def scaled_errors(panels: list[dict], center: str = "model", *, with_dates: bool = False) -> dict[int, list]:
    """Per horizon: ln(actual / forecast) / scale for every scored origin (finance excluded);
    with_dates=True gives rows {year, origin, known, z} for the out-of-sample check, where origin is the
    forecast's filing date and known the filing date of the 10-K that reported the actual."""
    out: dict[int, list] = {h: [] for h in HORIZONS}
    for p in panels:
        if division(p.get("sic")) == "Finance":
            continue
        for o in p["origins"]:
            if o["n_history"] < 3:
                continue
            f, s = o["revenue"].get(center) or {}, scale(o["history"])
            for h in HORIZONS:
                a = o["actual"].get(h)
                if a and a > 0 and f.get(h) and f[h] > 0:
                    e = math.log(a / f[h]) / s
                    out[h].append({"year": int(o["base_end"][:4]), "origin": o["origin"],
                                   "known": o["actual_origin"][h], "z": e} if with_dates else e)
    return out


def _q(sorted_v: list[float], p: float) -> float:
    i = p * (len(sorted_v) - 1)
    lo = int(i)
    hi = min(lo + 1, len(sorted_v) - 1)
    return sorted_v[lo] + (sorted_v[hi] - sorted_v[lo]) * (i - lo)


def known_quantiles(rows: list[dict], tests: list[dict], levels=(0.8, 0.9, 0.95)) -> list[tuple[int, dict]]:
    """For each test row: how many scaled errors were known by its origin date, and their central quantiles
    at each level ({level: (lo, hi)}). An error is known once the 10-K reporting its actual has been filed
    (row["known"] <= test["origin"]); a fiscal year having ended is not enough. One sweep in date order."""
    pending = sorted(rows, key=lambda r: r["known"])
    out: list[tuple[int, dict]] = [(0, {})] * len(tests)
    cal: list[float] = []
    j = 0
    for i in sorted(range(len(tests)), key=lambda i: tests[i]["origin"]):
        while j < len(pending) and pending[j]["known"] <= tests[i]["origin"]:
            insort(cal, pending[j]["z"])
            j += 1
        if cal:
            out[i] = (len(cal), {lvl: (_q(cal, (1 - lvl) / 2), _q(cal, 1 - (1 - lvl) / 2)) for lvl in levels})
    return out


def tested_coverage(rows: dict[int, list[dict]], levels=(0.8, 0.9, 0.95),
                    first_year: int = 2014, min_calibration: int = 200) -> dict:
    """Out of sample and point in time: each forecast from base year `first_year` on is scored with quantiles
    of the errors known on its filing date (known_quantiles), the way the model would have been calibrated
    on the day. rows: scaled_errors(..., with_dates=True)."""
    hits = {lvl: {} for lvl in levels}
    for h, rs in rows.items():
        tests = [r for r in rs if r["year"] >= first_year]
        scored = [(r, q) for r, (n, q) in zip(tests, known_quantiles(rs, tests, levels)) if n >= min_calibration]
        if not scored:
            continue
        for lvl in levels:
            k = sum(q[lvl][0] <= r["z"] <= q[lvl][1] for r, q in scored)
            hits[lvl][str(h)] = {"coverage": round(k / len(scored), 4), "n": len(scored)}
    return {"method": f"expanding window: forecasts from base year {first_year} on, each scored with quantiles "
                      f"from errors whose actuals were filed by its own filing date",
            "levels": {f"{round(lvl * 100)}": by_h for lvl, by_h in hits.items()}}


def table(errors: dict[int, list[float]], *, center: str, source: str, as_of: str, tested: dict | None = None) -> dict:
    """The file the Valuation Model reads: scaled-error quantiles on GRID for each horizon."""
    return {
        "what": "Quantiles of ln(actual revenue / forecast) divided by (revenue volatility + floor), by years out",
        "center": center, "scale": {"floor": SCALE_FLOOR, "default_vol": DEFAULT_VOL,
                                    "vol": "pstdev of yearly log revenue growth, up to 6 annual values"},
        "source": source, "as_of": as_of,
        "n": {str(h): len(v) for h, v in errors.items()},
        "p": GRID,
        "quantiles": {str(h): [round(_q(sorted(v), p), 5) for p in GRID] for h, v in errors.items() if v},
        "tested": tested,
    }
