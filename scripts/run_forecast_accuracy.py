"""Study 1, end to end: universe -> company facts -> panels -> results.

    export SEC_USER_AGENT="Your Name you@example.com"     # the SEC requires contact details
    python scripts/run_forecast_accuracy.py                # everything, resuming where it left off
    python scripts/run_forecast_accuracy.py --limit 25     # a quick run on the first 25 companies

Downloads go to data/ (gitignored): each company's facts are cut to the tags the
Valuation Model reads and gzipped, so the full universe stays small. The published
result is site/data/forecast_accuracy.json. Every stage skips work already on disk.
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from datetime import date
from pathlib import Path

from valuation.L0_ingest.cache import FileCache
from valuation.L0_ingest.http import HttpError
from valuation.L0_ingest.sec_sector import REVENUE_TAGS, SecSectorAdapter

from research.forecast_accuracy import study, universe
from research.forecast_accuracy.panel import company_panel, keep_tags

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "forecast_accuracy"
OUT = ROOT / "site" / "data" / "forecast_accuracy.json"


def engine_version() -> str:
    from importlib.metadata import version
    return f"valuation {version('valuation')} @ {(ROOT / 'ENGINE').read_text().strip()[:7]}"


def build_universe(sec: SecSectorAdapter) -> list[dict]:
    path = DATA / "universe.json"
    if path.exists():
        return json.loads(path.read_text())
    frames = {}
    for y in universe.COHORT_YEARS:
        rows = []
        for tag in REVENUE_TAGS:
            rows += sec.frame(tag, f"CY{y}") or []
        frames[y] = rows
    chosen = universe.select(frames)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(chosen, indent=1))
    return chosen


def facts_for(sec: SecSectorAdapter, cik: str) -> dict | None:
    path = DATA / "facts" / f"CIK{cik}.json.gz"
    if path.exists():
        return json.loads(gzip.decompress(path.read_bytes()))
    try:
        raw = keep_tags(sec.fetch(cik=cik))
    except HttpError as e:
        if e.status == 404:
            return None
        raise
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(json.dumps(raw).encode()))
    return raw


def panel_for(raw: dict, cik: str) -> dict:
    path = DATA / "panels" / f"CIK{cik}.json"
    if path.exists():
        return json.loads(path.read_text(), object_hook=_int_keys)
    p = company_panel(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(p))
    return json.loads(path.read_text(), object_hook=_int_keys)


def _int_keys(d: dict) -> dict:
    """Horizons are ints in memory and strings in JSON."""
    return {int(k) if isinstance(k, str) and k.isdigit() else k: v for k, v in d.items()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--limit", type=int, help="only the first N companies of the universe")
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args(argv)

    sec = SecSectorAdapter(cache=FileCache(ROOT / ".cache" / "sec", ttl_seconds=None))
    chosen = build_universe(sec)[: a.limit]
    panels = []
    for i, c in enumerate(chosen, 1):
        raw = facts_for(sec, c["cik"])
        if raw and raw["facts"]:
            panels.append(panel_for(raw, c["cik"]))
        if i % 25 == 0:
            print(f"{i}/{len(chosen)} companies", file=sys.stderr)
    result = study.run(panels, engine=engine_version(), as_of=date.today().isoformat(), universe_size=len(chosen))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(result, indent=1))
    s = result["sample"]
    print(f"{s['companies_scored']} companies, {s['observations']} observations -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
