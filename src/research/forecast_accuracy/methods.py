"""Forecasts made at one origin from point-in-time history.

Revenue, h years after the base year (R0 = base-year revenue):
  naive     R0. The no-change forecast every method has to beat.
  hist3     R0 * (1 + g3)^h, g3 = the company's own revenue CAGR over up to three years.
  sector    R0 * (1 + gs)^h, gs = median g3 across the sector at the same origin year
            (filled in by the study runner, which sees the cross-section).
  model     the Valuation Model's default DCF case: growth g0 from the company's history
            (capped -5%..20%) fading linearly to 2.5% over ten years. Same engine, same caps.

Range: the model's simulation draws near-term growth from a triangular distribution
g0 +/- 3 points. Revenue at any horizon rises with g0, so its P10 and P90 are the
revenue paths at g0's own P10 and P90; no sampling needed, and the answer is exact.

Operating margin (operating income / revenue):
  naive     the base-year margin. The model's trend case holds cost ratios at the base
            year, so its margin forecast is the same number.
  hist3     the mean margin over up to three years.
"""
from __future__ import annotations

import math

from valuation.L2_models.dcf import DEFAULT_TERMINAL_GROWTH, GROWTH_CAP, SIMULATION

HORIZONS = (1, 2, 3, 4, 5)
FADE_YEARS = 10                       # the default DCF's years to terminal
SPREAD = SIMULATION["growth_spread"]  # triangular half-width on near-term growth
RANGE = (0.10, 0.90)                  # Bear and Bull on the site


def cagr(history: list[float], years: int = 3) -> float | None:
    """Compound growth over the last `years` intervals (fewer if history is shorter)."""
    h = [v for v in history if v is not None]
    n = min(years, len(h) - 1)
    if n < 1 or h[-1 - n] <= 0 or h[-1] <= 0:
        return None
    return (h[-1] / h[-1 - n]) ** (1 / n) - 1


def fade_path(r0: float, g0: float, horizon: int, g_terminal: float = DEFAULT_TERMINAL_GROWTH,
              fade_years: int = FADE_YEARS) -> list[float]:
    """Revenue for years 1..horizon with growth fading linearly from g0 (the engine's fade rule)."""
    out, r = [], r0
    for t in range(1, horizon + 1):
        g = g0 - (t - 1) * (g0 - g_terminal) / fade_years
        r *= 1 + g
        out.append(r)
    return out


def tri_quantile(p: float, low: float, mode: float, high: float) -> float:
    """Inverse CDF of the triangular distribution."""
    c = (mode - low) / (high - low)
    if p < c:
        return low + math.sqrt(p * (high - low) * (mode - low))
    return high - math.sqrt((1 - p) * (high - low) * (high - mode))


def model_g0(trend_g0: float | None) -> float:
    """The default DCF case's near-term growth from the trend case's (missing -> 5%, as the engine does)."""
    g = 0.05 if trend_g0 is None else trend_g0
    return min(max(g, GROWTH_CAP[0]), GROWTH_CAP[1])


def revenue_forecasts(history: list[float], trend_g0: float | None, horizons=HORIZONS) -> dict:
    """{method: {h: forecast}} plus the model's P10/P90 band, for one origin."""
    r0 = history[-1]
    H = max(horizons)
    g3 = cagr(history)
    g0 = model_g0(trend_g0)
    lo, hi = (fade_path(r0, tri_quantile(p, g0 - SPREAD, g0, g0 + SPREAD), H) for p in RANGE)
    mid = fade_path(r0, g0, H)
    out = {"naive": {h: r0 for h in horizons},
           "model": {h: mid[h - 1] for h in horizons},
           "model_p10": {h: lo[h - 1] for h in horizons},
           "model_p90": {h: hi[h - 1] for h in horizons}}
    if g3 is not None:
        out["hist3"] = {h: r0 * (1 + g3) ** h for h in horizons}
    return {"forecasts": out, "g3": g3, "g0_model": g0}


def sector_forecasts(r0: float, sector_g: float | None, horizons=HORIZONS) -> dict[int, float] | None:
    return None if sector_g is None else {h: r0 * (1 + sector_g) ** h for h in horizons}


def margin_forecasts(margins: list[float | None], horizons=HORIZONS) -> dict:
    m = [x for x in margins if x is not None]
    if not m:
        return {}
    out = {"naive": {h: m[-1] for h in horizons}}
    tail = m[-3:]
    out["hist3"] = {h: sum(tail) / len(tail) for h in horizons}
    return out
