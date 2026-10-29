"""One company's forecast panel: an origin at every 10-K, and what came true.

An origin is the day a 10-K was filed. Everything at that origin comes from the
Valuation Model's normalizer run as of that day, so only facts filed on or before
it count (the engine drops the rest). The actual for a later year is that year's
revenue as first reported in its own 10-K: the base year of a later origin. Both
sides are point in time; restatements made after the fact never leak in.
"""
from __future__ import annotations

from datetime import date

from valuation.L1_detail.build import build_detail
from valuation.L1_detail.normalize import normalize
from valuation.L1_detail.registry import load_registry

from .methods import HORIZONS, margin_forecasts, revenue_forecasts

MAX_BASE_AGE_DAYS = 150    # the base year must end within ~5 months of the filing
MATCH_DAYS = 25            # a target year's end may drift this much (52/53-week years)
HISTORY_YEARS = 6


def keep_tags(raw: dict) -> dict:
    """Drop facts the registry never reads. Same result, a fraction of the size on disk."""
    tags = {t for c in load_registry().concepts.values() for t in c.all_tags()}
    facts = [f for f in raw["facts"] if f["taxonomy"] == "dei" or f"{f['taxonomy']}:{f['tag']}" in tags]
    return {**raw, "facts": facts}


def origins(raw: dict) -> list[str]:
    """Filing dates of original annual reports (10-K, fiscal year), earliest per fiscal year."""
    first: dict[int, str] = {}
    for f in raw["facts"]:
        if f.get("form") == "10-K" and f.get("fp") == "FY" and f.get("filed") and f.get("fy"):
            fy = int(f["fy"])
            first[fy] = min(first.get(fy, f["filed"]), f["filed"])
    return sorted(set(first.values()))


def _d(s: str) -> date:
    return date.fromisoformat(s)


def _chain(annual: list[dict]) -> list[dict]:
    """The run of consecutive fiscal years (ends ~1 year apart) ending at the latest year with revenue."""
    rows = [p for p in annual if p["values"].get("revenue") not in (None, 0)]
    if not rows:
        return []
    out = [rows[-1]]
    for p in reversed(rows[:-1]):
        gap = (_d(out[0]["end"]) - _d(p["end"])).days
        if abs(gap - 365) > MATCH_DAYS:
            break
        out.insert(0, p)
    return out[-HISTORY_YEARS:]


class EngineError(Exception):
    """The engine couldn't build this origin (bad filed data it doesn't guard against)."""


def origin_record(raw: dict, as_of: str) -> dict | None:
    """What the model knew and forecast on one filing date; None if there's no usable base year."""
    try:
        detail = build_detail(normalize(raw, as_of), as_of)
    except ValueError:
        return None
    except (TypeError, ZeroDivisionError) as e:
        # e.g. a negative revenue fact makes the engine's CAGR complex; counted, not hidden
        raise EngineError(str(e)) from e
    chain = _chain(detail["views"]["annual"])
    if not chain or (_d(as_of) - _d(chain[-1]["end"])).days > MAX_BASE_AGE_DAYS:
        return None
    rev = [p["values"]["revenue"] for p in chain]
    if rev[-1] <= 0:
        return None
    margins = [(p["values"].get("operating_income_loss") / p["values"]["revenue"])
               if p["values"].get("operating_income_loss") is not None else None for p in chain]
    trend_g0 = ((detail.get("projection") or {}).get("assumptions") or {}).get("revenue_growth_start")
    fc = revenue_forecasts(rev, trend_g0)
    return {"origin": as_of, "base_end": chain[-1]["end"], "base_fy": chain[-1].get("fiscal_year"),
            "r0": rev[-1], "margin0": margins[-1], "history": rev, "n_history": len(rev),
            "g3": fc["g3"], "g0_model": fc["g0_model"], "trend_g0": trend_g0,
            "revenue": fc["forecasts"], "margin": margin_forecasts(margins)}


def company_panel(raw: dict) -> dict:
    """Every origin for one company, each with the actuals that later origins reported."""
    ent = raw.get("entity") or {}
    recs, skipped = [], 0
    for d in origins(raw):
        try:
            r = origin_record(raw, d)
        except EngineError:
            skipped += 1
            continue
        if r:
            recs.append(r)
    # one record per base year: if two filings share a base year, keep the earlier
    by_base: dict[str, dict] = {}
    for r in recs:
        by_base.setdefault(r["base_end"], r)
    recs = sorted(by_base.values(), key=lambda r: r["base_end"])
    for r in recs:
        r["actual"], r["actual_margin"], r["actual_origin"] = {}, {}, {}
        for h in HORIZONS:
            target = _d(r["base_end"]).replace(year=_d(r["base_end"]).year + h) if not r["base_end"].endswith("02-29") \
                else date(_d(r["base_end"]).year + h, 2, 28)
            hit = next((o for o in recs if abs((_d(o["base_end"]) - target).days) <= MATCH_DAYS), None)
            if hit:
                r["actual"][h] = hit["r0"]
                r["actual_margin"][h] = hit["margin0"]
                r["actual_origin"][h] = hit["origin"]
        # largest one-year revenue move between base and the furthest actual: flags acquisitions and spin-offs
        path = [r["r0"]] + [r["actual"][h] for h in HORIZONS if h in r["actual"]]
        moves = [abs(b / a - 1) for a, b in zip(path, path[1:]) if a > 0]
        r["max_yoy_move"] = max(moves) if moves else None
    return {"cik": ent.get("cik"), "name": ent.get("name"), "sic": ent.get("sic"), "origins": recs,
            "engine_errors": skipped}
