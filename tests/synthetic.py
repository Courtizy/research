"""Synthetic SEC company facts for offline tests: no network, known answers.

`company()` writes facts the way the companyfacts API reports them: each 10-K
carries the current year and two prior years as comparatives, all stamped with
that filing's date, fiscal year and accession number.
"""
from __future__ import annotations

REV_TAG = "RevenueFromContractWithCustomerExcludingAssessedTax"


def _fact(tag, value, start, end, fy, filed, accn, form="10-K", fp="FY"):
    return {"taxonomy": "us-gaap", "tag": tag, "label": tag, "description": None, "unit": "USD",
            "value": value, "start": start, "end": end, "fy": fy, "fp": fp, "form": form,
            "filed": filed, "accn": accn, "frame": None}


def company(revenue: dict[int, float], margin: dict[int, float] | float = 0.10, *, cik="0000000001",
            name="Synthetic Co", sic="3720", filed_month_day="02-15", restate: dict | None = None) -> dict:
    """A raw_filing dict for a calendar-year filer. revenue: {fiscal year: value}.
    restate: {(filing_fy, year): value} overrides a comparative inside a later 10-K."""
    years = sorted(revenue)
    restate = restate or {}
    m = (lambda y: margin[y]) if isinstance(margin, dict) else (lambda y: margin)
    facts = []
    for fy in years:
        filed = f"{fy + 1}-{filed_month_day}"
        accn = f"0000000001-{(fy + 1) % 100:02d}-{fy:06d}"
        for y in (fy - 2, fy - 1, fy):
            if y not in revenue:
                continue
            rev = restate.get((fy, y), revenue[y])
            start, end = f"{y}-01-01", f"{y}-12-31"
            facts.append(_fact(REV_TAG, rev, start, end, fy, filed, accn))
            facts.append(_fact("OperatingIncomeLoss", round(rev * m(y), 2), start, end, fy, filed, accn))
    facts.sort(key=lambda f: (f["tag"], f["end"], f["filed"]))
    return {"schema_version": "1.0", "source": "synthetic", "source_url": None, "content_sha256": None,
            "entity": {"cik": cik, "name": name, "ticker": None, "sic": sic, "sic_description": None},
            "facts": facts}
