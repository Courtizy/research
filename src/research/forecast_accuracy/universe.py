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
