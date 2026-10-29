"""Scoring the forecasts: error, bias, skill against the naive forecast, and range coverage.

Errors are log ratios, e = ln(forecast / actual): symmetric, scale-free, and
e = +0.10 means the forecast was about 10% too high. Every standard error is
clustered by company, because one company's origins overlap and share its
surprises; treating them as independent would overstate confidence.
"""
from __future__ import annotations

import math
from collections import defaultdict
from statistics import median

from .methods import HORIZONS

DIVISIONS = [  # SIC divisions; finance (60-67) is excluded upstream, revenue means little for banks
    (1, 9, "Agriculture"), (10, 14, "Mining and energy"), (15, 17, "Construction"),
    (20, 39, "Manufacturing"), (40, 49, "Transport, comms and utilities"), (50, 51, "Wholesale"),
    (52, 59, "Retail"), (60, 67, "Finance"), (70, 89, "Services"), (90, 99, "Public administration")]


def division(sic: str | None) -> str | None:
    if not sic or not str(sic)[:2].isdigit():
        return None
    two = int(str(sic)[:2])
    return next((name for lo, hi, name in DIVISIONS if lo <= two <= hi), None)


def norm_p(z: float) -> float:
    """Two-sided p-value for a z statistic."""
    return math.erfc(abs(z) / math.sqrt(2))


def clustered_mean(values: list[float], clusters: list[str]) -> dict:
    """Mean with a company-clustered standard error, t statistic and p-value (normal approximation)."""
    n = len(values)
    if n == 0:
        return {"n": 0, "clusters": 0, "mean": None, "se": None, "t": None, "p": None}
    m = sum(values) / n
    sums: dict[str, float] = defaultdict(float)
    for v, c in zip(values, clusters):
        sums[c] += v - m
    g = len(sums)
    if g < 2:
        return {"n": n, "clusters": g, "mean": m, "se": None, "t": None, "p": None}
    se = math.sqrt(g / (g - 1) * sum(s * s for s in sums.values())) / n
    t = m / se if se > 0 else None
    return {"n": n, "clusters": g, "mean": m, "se": se, "t": t, "p": norm_p(t) if t is not None else None}


def quantile(xs: list[float], q: float) -> float:
    s = sorted(xs)
    i = (len(s) - 1) * q
    lo, hi = math.floor(i), math.ceil(i)
    return s[lo] + (s[hi] - s[lo]) * (i - lo)


def winsorize(xs: list[float], p: float = 0.01) -> list[float]:
    if len(xs) < 20:
        return list(xs)
    lo, hi = quantile(xs, p), quantile(xs, 1 - p)
    return [min(max(x, lo), hi) for x in xs]


def observations(panels: list[dict], *, min_history: int = 3) -> list[dict]:
    """One row per company x origin x horizon with an actual: every method's revenue forecast,
    the model's band and the margin forecasts. Panels must already carry sector forecasts."""
    rows = []
    for p in panels:
        for o in p["origins"]:
            if o["n_history"] < min_history:
                continue
            for h in HORIZONS:
                a = o["actual"].get(h)
                if not a or a <= 0:
                    continue
                rev = {m: f[h] for m, f in o["revenue"].items() if f and f.get(h) and f[h] > 0}
                rows.append({
                    "cik": p["cik"], "division": division(p.get("sic")), "h": h,
                    "base_year": int(o["base_end"][:4]), "g3": o["g3"], "g0_model": o["g0_model"],
                    "large_move": (o.get("max_yoy_move") or 0) > 0.5,
                    "actual": a, "err": {m: math.log(v / a) for m, v in rev.items() if not m.startswith("model_p")},
                    "in_band": rev["model_p10"] <= a <= rev["model_p90"],
                    "below_band": a < rev["model_p10"],
                    "margin_actual": o["actual_margin"].get(h),
                    "margin_err": {m: f[h] - o["actual_margin"][h] for m, f in o["margin"].items()
                                   if o["actual_margin"].get(h) is not None},
                })
    return rows


def accuracy(rows: list[dict], methods=("naive", "hist3", "sector", "model")) -> list[dict]:
    """Per method and horizon: median absolute error, bias, and skill against naive (same rows)."""
    out = []
    for h in HORIZONS:
        hr = [r for r in rows if r["h"] == h]
        for m in methods:
            rs = [r for r in hr if m in r["err"] and "naive" in r["err"]]
            if not rs:
                continue
            e = [r["err"][m] for r in rs]
            cl = [r["cik"] for r in rs]
            ae = [abs(x) for x in winsorize(e)]
            ae_naive = [abs(x) for x in winsorize([r["err"]["naive"] for r in rs])]
            diff = clustered_mean([a - b for a, b in zip(ae, ae_naive)], cl)
            out.append({
                "h": h, "method": m, "n": len(rs), "companies": len(set(cl)),
                "median_abs_error": median(abs(x) for x in e),
                "p90_abs_error": quantile([abs(x) for x in e], 0.9),
                "bias": clustered_mean(winsorize(e), cl),
                "skill_vs_naive": 1 - (sum(ae) / sum(ae_naive)) if sum(ae_naive) else None,
                "loss_diff_vs_naive": diff,   # mean |e| minus naive's, < 0 = better (Diebold-Mariano style)
            })
    return out


def coverage(rows: list[dict], nominal: float = 0.80) -> list[dict]:
    """How often the actual fell inside the model's P10-P90 band, by horizon, tested against 80%."""
    out = []
    for h in HORIZONS:
        rs = [r for r in rows if r["h"] == h]
        if not rs:
            continue
        cl = [r["cik"] for r in rs]
        cov = clustered_mean([1.0 if r["in_band"] else 0.0 for r in rs], cl)
        z = (cov["mean"] - nominal) / cov["se"] if cov["se"] else None
        out.append({"h": h, "n": len(rs), "coverage": cov["mean"], "se": cov["se"],
                    "below": sum(r["below_band"] for r in rs) / len(rs),
                    "above": sum(not r["in_band"] and not r["below_band"] for r in rs) / len(rs),
                    "z_vs_nominal": z, "p_vs_nominal": norm_p(z) if z is not None else None})
    return out


def bias_by_growth(rows: list[dict], h: int = 3, groups: int = 10, methods=("model", "hist3")) -> list[dict]:
    """Mean error by prior-growth decile at one horizon: does the past fast grower get over-forecast? (H1)"""
    rs = sorted((r for r in rows if r["h"] == h and r["g3"] is not None), key=lambda r: r["g3"])
    if len(rs) < groups * 5:
        return []
    out = []
    for k in range(groups):
        chunk = rs[k * len(rs) // groups:(k + 1) * len(rs) // groups]
        row = {"group": k + 1, "n": len(chunk), "g3_median": median(r["g3"] for r in chunk)}
        for m in methods:
            sub = [r for r in chunk if m in r["err"]]
            row[m] = clustered_mean([r["err"][m] for r in sub], [r["cik"] for r in sub])
        out.append(row)
    return out


def margin_accuracy(rows: list[dict]) -> list[dict]:
    """Operating margin: absolute error in percentage points, hist3 mean against the no-change forecast (H2)."""
    out = []
    for h in HORIZONS:
        rs = [r for r in rows if r["h"] == h and "naive" in r["margin_err"] and "hist3" in r["margin_err"]]
        if not rs:
            continue
        cl = [r["cik"] for r in rs]
        a_n = [abs(x) for x in winsorize([r["margin_err"]["naive"] for r in rs])]
        a_h = [abs(x) for x in winsorize([r["margin_err"]["hist3"] for r in rs])]
        out.append({"h": h, "n": len(rs), "median_abs_pp": {"naive": median(a_n) * 100, "hist3": median(a_h) * 100},
                    "loss_diff_hist3_vs_naive": clustered_mean([b - a for a, b in zip(a_n, a_h)], cl)})
    return out


def by_division(rows: list[dict], h: int = 3) -> list[dict]:
    """Model and hist3 skill against naive by sector division, at one horizon."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r["h"] == h and r["division"]:
            groups[r["division"]].append(r)
    out = []
    for d, rs in sorted(groups.items()):
        if len({r["cik"] for r in rs}) < 10:
            continue
        row = {"division": d, "n": len(rs), "companies": len({r["cik"] for r in rs})}
        for m in ("model", "hist3"):
            sub = [r for r in rs if m in r["err"]]
            ae = sum(abs(r["err"][m]) for r in sub)
            an = sum(abs(r["err"]["naive"]) for r in sub)
            row[m] = 1 - ae / an if an else None
        out.append(row)
    return out
