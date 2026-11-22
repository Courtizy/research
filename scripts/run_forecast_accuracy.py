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
import os
import sys
from datetime import date
from pathlib import Path

from valuation.L0_ingest.cache import FileCache
from valuation.L0_ingest.http import HttpError
from valuation.L0_ingest.sec_sector import REVENUE_TAGS, SecSectorAdapter

from research import provenance
from research.forecast_accuracy import study, universe
from research.forecast_accuracy.panel import company_panel, keep_tags

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "forecast_accuracy"
OUT = ROOT / "site" / "data" / "forecast_accuracy.json"


def engine_version() -> str:
    """"valuation <version> @ <commit>", read from the engine checkout itself. Package metadata from an
    earlier `pip install -e` can name an older version after the checkout moves, so it isn't used, and a
    checkout that isn't at the commit pinned in ENGINE is refused."""
    import re
    import subprocess

    import valuation
    repo = Path(valuation.__file__).resolve().parents[2]
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip()
    pinned = (ROOT / "ENGINE").read_text().strip()
    if head != pinned:
        raise SystemExit(f"engine checkout {repo} is at {head[:7]}, ENGINE pins {pinned[:7]}: run scripts/setup_engine.sh")
    version = re.search(r'^version\s*=\s*"([^"]+)"', (repo / "pyproject.toml").read_text(), re.M).group(1)
    return f"valuation {version} @ {head[:7]}"


def revenue_frames(sec: SecSectorAdapter) -> dict[int, list]:
    frames = {}
    for y in universe.COHORT_YEARS:
        rows = []
        for tag in REVENUE_TAGS:
            rows += sec.frame(tag, f"CY{y}") or []
        frames[y] = rows
    return frames


def build_universe(sec: SecSectorAdapter) -> list[dict]:
    path = DATA / "universe.json"
    if path.exists():
        return json.loads(path.read_text())
    chosen = universe.select(revenue_frames(sec))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(chosen, indent=1))
    return chosen


def facts_for(sec: SecSectorAdapter, cik: str, data: Path = DATA) -> dict | None:
    path = data / "facts" / f"CIK{cik}.json.gz"
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


def panel_for(raw: dict, cik: str, data: Path = DATA) -> dict:
    path = data / "panels" / f"CIK{cik}.json"
    if path.exists():
        return json.loads(path.read_text(), object_hook=_int_keys)
    p = company_panel(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(p))
    return json.loads(path.read_text(), object_hook=_int_keys)


def sec_adapter() -> SecSectorAdapter:
    return SecSectorAdapter(cache=FileCache(ROOT / ".cache" / "sec", ttl_seconds=None))


def load_panels(sec: SecSectorAdapter, chosen: list[dict], data: Path = DATA) -> list[dict]:
    """Each company's panel, fetching and building what isn't on disk yet."""
    panels = []
    for i, c in enumerate(chosen, 1):
        raw = facts_for(sec, c["cik"], data)
        if raw and raw["facts"]:
            panels.append(panel_for(raw, c["cik"], data))
        if i % 25 == 0:
            print(f"{i}/{len(chosen)} companies", file=sys.stderr)
    return panels


def _int_keys(d: dict) -> dict:
    """Horizons are ints in memory and strings in JSON."""
    return {int(k) if isinstance(k, str) and k.isdigit() else k: v for k, v in d.items()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--limit", type=int, help="only the first N companies of the universe")
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args(argv)

    sec = sec_adapter()
    chosen = build_universe(sec)[: a.limit]
    panels = load_panels(sec, chosen)
    result = study.run(panels, engine=engine_version(), as_of=date.today().isoformat(), universe_size=len(chosen))
    result["run"] = provenance.run_info(dict(os.environ))       # which Actions run wrote this file, or "local"
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(result, indent=1))
    s = result["sample"]
    print(f"{s['companies_scored']} companies, {s['observations']} observations -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
