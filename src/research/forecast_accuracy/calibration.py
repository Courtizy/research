"""Calibrated revenue ranges: quantiles of the model's past misses, for the Valuation Model.

The model's range used to come from a +/-3% triangular wobble in growth and held about 14% of
outcomes. Here the range is the spread of what actually happened: the log error of the model's
forecast (ln actual / forecast) at each horizon, divided by a company scale so steady companies
get narrow ranges and volatile ones wide ranges. Scale = the standard deviation of the company's
yearly log revenue growth over its history, plus SCALE_FLOOR.

Out of sample (each base year scored with quantiles from errors already known by then), a range
built for 90% held 88-93% and one built for 95% held 94-97% across horizons 1-5.
"""
from __future__ import annotations

import math
from statistics import pstdev

from collections import defaultdict
from statistics import median

from .methods import HORIZONS
from .metrics import division

SCALE_FLOOR = 0.10            # added to volatility, so a company with a smooth history still gets a range
DEFAULT_VOL = 0.10            # when the history is too short to measure
GRID = [round(0.005 * i, 3) for i in range(1, 200)]   # 0.5% steps, so P2.5, P5, P10 ... P97.5 are exact


def add_blend(panels: list[dict]) -> None:
    """The blended forecast: the geometric mean of no change, the model's fade and the sector's growth
    (the model when there's no sector forecast). Out of sample it beat no change by 7% three years out
    and 12% five years out, where the fade alone did not. Panels must already carry sector forecasts."""
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


def scaled_errors(panels: list[dict], center: str = "model") -> dict[int, list[float]]:
    """Per horizon: ln(actual / forecast) / scale for every scored origin (finance excluded)."""
    out: dict[int, list[float]] = {h: [] for h in HORIZONS}
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
                    out[h].append(math.log(a / f[h]) / s)
    return out


def _q(sorted_v: list[float], p: float) -> float:
    i = p * (len(sorted_v) - 1)
    lo = int(i)
    hi = min(lo + 1, len(sorted_v) - 1)
    return sorted_v[lo] + (sorted_v[hi] - sorted_v[lo]) * (i - lo)


def table(errors: dict[int, list[float]], *, center: str, source: str, as_of: str) -> dict:
    """The file the Valuation Model reads: scaled-error quantiles on GRID for each horizon."""
    return {
        "what": "Quantiles of ln(actual revenue / forecast) divided by (revenue volatility + floor), by years out",
        "center": center, "scale": {"floor": SCALE_FLOOR, "default_vol": DEFAULT_VOL,
                                    "vol": "pstdev of yearly log revenue growth, up to 6 annual values"},
        "source": source, "as_of": as_of,
        "n": {str(h): len(v) for h, v in errors.items()},
        "p": GRID,
        "quantiles": {str(h): [round(_q(sorted(v), p), 5) for p in GRID] for h, v in errors.items() if v},
    }
