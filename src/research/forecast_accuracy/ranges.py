"""Revenue ranges scored out of sample and point in time.

Two ways of drawing a range around a forecast are compared on the same observations:
  simulated   the Valuation Model's original P10-P90 band, from a +/-3 point triangular wobble in growth
  calibrated  quantiles of past misses of the blended forecast, scaled by how volatile the company's
              revenue has been (calibration.py), at 80%, 90% and 95%

Each forecast from base year 2014 on is scored with quantiles built only from errors whose actual had
been filed by that forecast's own filing date (a past fiscal year having ended is not enough; its 10-K
may not be out yet).
"""
from __future__ import annotations

import math
from bisect import insort
from collections import defaultdict
from statistics import median

from .calibration import _q, known_quantiles, scale
from .metrics import clustered_mean, division, norm_p, winsorize
from .methods import HORIZONS

EXCLUDED_DIVISIONS = {"Finance"}
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


def coverage_by_horizon(hits: list[dict], levels=LEVELS) -> list[dict]:
    """Per horizon: the simulated band against 80%, each calibrated range against its own level, and how wide each is."""
    out = []
    for h in HORIZONS:
        rs = [r for r in hits if r["h"] == h]
        if not rs:
            continue
        row = {"h": h, "n": len(rs), "companies": len({r["cik"] for r in rs}),
               "simulated": {**_share(rs, lambda r: r["old_hit"], 0.8),
                          "below": median(r["old_reach"][0] for r in rs), "above": median(r["old_reach"][1] for r in rs)},
               "calibrated": {}}
        for lvl in levels:
            row["calibrated"][str(round(lvl * 100))] = {
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
    return [{"group": g, "n": len(rs), "simulated": _share(rs, lambda r: r["old_hit"])["share"],
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
