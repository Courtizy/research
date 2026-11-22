"""Which companies are in the study.

Survivorship is the trap: today's company list leaves out every firm that was
acquired, went bankrupt or delisted, and those are exactly the forecasts that
missed. So the universe is built from the SEC's historical frames: the largest
filers by revenue in several past calendar years, taken together. A firm that
was large in 2011 is in the study even if it no longer files.
"""
from __future__ import annotations

COHORT_YEARS = (2011, 2015, 2019)
PER_COHORT = 300
MIN_REVENUE = 1e9


def select(frames: dict[int, list[list]], per_cohort: int = PER_COHORT, min_revenue: float = MIN_REVENUE) -> list[dict]:
    """frames: {year: rows [cik, name, start, end, val] across the revenue tags}. Returns the union of
    each cohort's largest filers, with the cohorts each one came from."""
    chosen: dict[str, dict] = {}
    for year, rows in sorted(frames.items()):
        best: dict[str, tuple[float, str]] = {}
        for cik, name, _start, _end, val in rows:
            if cik is None or val is None:
                continue
            k = str(cik).zfill(10)
            if val > best.get(k, (float("-inf"), ""))[0]:
                best[k] = (val, name)
        top = sorted(((v, k, n) for k, (v, n) in best.items() if v >= min_revenue), reverse=True)[:per_cohort]
        for v, k, n in top:
            chosen.setdefault(k, {"cik": k, "name": n, "cohorts": []})["cohorts"].append(year)
    return sorted(chosen.values(), key=lambda c: c["cik"])


HELD_OUT_BAND = (250e6, 1e9)
HELD_OUT_PER_COHORT = 300


def _draw_key(cik: str) -> str:
    import hashlib
    return hashlib.sha256(cik.encode()).hexdigest()


def select_held_out(frames: dict[int, list[list]], exclude: set[str], band: tuple[float, float] = HELD_OUT_BAND,
                    per_cohort: int = HELD_OUT_PER_COHORT) -> list[dict]:
    """The held-out sample: in each cohort year, filers whose largest revenue that year is inside `band`
    (low inclusive), minus every CIK in `exclude` (Study 01's universe), drawn as the `per_cohort` with the
    lowest SHA-256 of their 10-digit CIK. A fixed rule, so nobody picks the companies."""
    chosen: dict[str, dict] = {}
    for year, rows in sorted(frames.items()):
        best: dict[str, tuple[float, str]] = {}
        for cik, name, _start, _end, val in rows:
            if cik is None or val is None:
                continue
            k = str(cik).zfill(10)
            if val > best.get(k, (float("-inf"), ""))[0]:
                best[k] = (val, name)
        eligible = [k for k, (v, _) in best.items() if band[0] <= v < band[1] and k not in exclude]
        for k in sorted(eligible, key=_draw_key)[:per_cohort]:
            chosen.setdefault(k, {"cik": k, "name": best[k][1], "cohorts": []})["cohorts"].append(year)
    return sorted(chosen.values(), key=lambda c: c["cik"])
