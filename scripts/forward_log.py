"""The forward scoreboard: log a forecast for every new 10-K, then score what later 10-Ks report.

    scripts/setup_engine.sh "$(python -c 'import json;print(json.load(open("forward/FREEZE.json"))["engine"])')"
    export SEC_USER_AGENT="Your Name you@example.com"
    python scripts/forward_log.py            # appends to forward/forecasts.jsonl, writes site/data/scoreboard.json

Runs weekly in GitHub Actions (forward.yml). Only 10-Ks filed on or after forward/FREEZE.json's frozen_on are
logged, with the frozen engine and calibration tables (checked before anything is fetched). The companies are
Study 01's and the held-out sample's, fixed in forward/universe.json on the first run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import valuation
from valuation._core.projection import _blend_path
from valuation.L0_ingest.sec_companyfacts import SUBMISSIONS_URL, SecCompanyFactsAdapter
from valuation.L1_detail.build import build_detail
from valuation.L1_detail.normalize import normalize
from valuation.L2_models.dcf import default_assumptions
from valuation.L2_models.dcf.revenue_range import band, company_scale, load_table

from research import forward
from research.forecast_accuracy import universe
from research.forecast_accuracy.metrics import division

ROOT = Path(__file__).resolve().parents[1]
FWD = ROOT / "forward"
LOG = FWD / "forecasts.jsonl"
UNIVERSE = FWD / "universe.json"
OUT = ROOT / "site" / "data" / "scoreboard.json"
MAX_BASE_AGE_DAYS = 150       # the base year must end within ~5 months of the filing, as in the studies


def check_engine(freeze: dict) -> Path:
    """Refuse to run on anything but the frozen engine and calibration tables."""
    repo = Path(valuation.__file__).resolve().parents[2]
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip()
    if head != freeze["engine"]:
        raise SystemExit(f"engine is at {head[:7]}, the scoreboard froze {freeze['engine'][:7]}")
    for rel, want in freeze["calibration_sha256"].items():
        got = hashlib.sha256((repo / rel).read_bytes()).hexdigest()
        if got != want:
            raise SystemExit(f"{rel} changed since the freeze")
    return repo


def build_universe(sec) -> list[dict]:
    """Study 01's companies plus the held-out sample, from the same SEC frames and rules."""
    from valuation.L0_ingest.sec_sector import REVENUE_TAGS
    frames = {}
    for y in universe.COHORT_YEARS:
        rows = []
        for tag in REVENUE_TAGS:
            rows += sec.frame(tag, f"CY{y}") or []
        frames[y] = rows
    s01 = universe.select(frames)
    held = universe.select_held_out(frames, exclude={c["cik"] for c in s01})
    return sorted([{"cik": c["cik"], "name": c["name"], "sample": "study01"} for c in s01]
                  + [{"cik": c["cik"], "name": c["name"], "sample": "held_out"} for c in held], key=lambda c: c["cik"])


def forecast(raw: dict, filed: str, table: dict) -> dict | str:
    """The default DCF's base case for years 1-5 and its calibrated 80%/90% ranges, as of the filing day.
    Returns a reason string when there's nothing to forecast."""
    if division(raw["entity"].get("sic")) == "Finance":
        return "finance"
    try:
        detail = build_detail(normalize(raw, filed), filed)
    except Exception as e:  # noqa: BLE001  bad filed data the engine doesn't guard against: counted, not fatal
        return f"engine: {type(e).__name__}"
    annual = (detail.get("views") or {}).get("annual") or []
    if not annual or not annual[-1]["values"].get("revenue") or annual[-1]["values"]["revenue"] <= 0:
        return "no revenue"
    base = annual[-1]
    age = (datetime.fromisoformat(filed) - datetime.fromisoformat(base["end"])).days
    if age > MAX_BASE_AGE_DAYS:
        return "stale base year"
    fc = default_assumptions(detail)["forecast"]
    r0 = base["values"]["revenue"]
    path = _blend_path({"method": "fade", "g0": fc["revenue_growth"], "g_terminal": fc["terminal_growth"],
                        "fade_years": fc["years_to_terminal"], "sector_growth": fc["sector_growth"], "blend_years": 5},
                       r0, 5)
    scale, _ = company_scale(detail, table)
    rng = {lvl: {str(b["year"]): [path[b["year"] - 1] * b["low"], path[b["year"] - 1] * b["high"]]
                 for b in rows if b["year"] <= 5} for lvl, rows in band(table, scale).items()}
    return {"base_end": base["end"], "base_revenue": r0, "g0": fc["revenue_growth"],
            "sector_growth": fc["sector_growth"], "scale": scale,
            "forecast": {str(h): path[h - 1] for h in forward.HORIZONS}, "range": rng}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--limit", type=int, help="only the first N companies (a plumbing check; writes nothing)")
    a = ap.parse_args(argv)

    freeze = json.loads((FWD / "FREEZE.json").read_text())
    check_engine(freeze)
    table = load_table()
    sec = SecCompanyFactsAdapter()            # no cache: every run must see the latest filings
    if UNIVERSE.exists():
        companies = json.loads(UNIVERSE.read_text())
    else:
        from valuation.L0_ingest.sec_sector import SecSectorAdapter
        companies = build_universe(SecSectorAdapter())
        if not a.limit:
            UNIVERSE.write_text(json.dumps(companies, indent=1) + "\n")
    log = forward.read(LOG)
    if not forward.verify(log):
        raise SystemExit("forward/forecasts.jsonl fails its hash chain: an earlier record was changed")
    seen = {r["accn"] for r in log}
    skipped: dict[str, int] = {}
    added = 0
    for i, c in enumerate(companies[: a.limit], 1):
        try:
            sub = json.loads(sec.client.get_bytes(SUBMISSIONS_URL.format(cik=c["cik"])))
        except Exception as e:  # noqa: BLE001  a company that stopped filing, or a transient error: next week
            skipped[f"submissions: {type(e).__name__}"] = skipped.get(f"submissions: {type(e).__name__}", 0) + 1
            continue
        todo = forward.new_10ks(sub, freeze["frozen_on"], seen)
        if not todo:
            continue
        try:
            raw = sec.fetch(cik=c["cik"])
        except Exception as e:  # noqa: BLE001
            skipped[f"facts: {type(e).__name__}"] = skipped.get(f"facts: {type(e).__name__}", 0) + 1
            continue
        for f in todo:
            got = forecast(raw, f["filed"], table)
            if isinstance(got, str):
                skipped[got] = skipped.get(got, 0) + 1
                continue
            forward.append(log, {"cik": c["cik"], "name": raw["entity"].get("name") or c["name"],
                                 "sample": c["sample"], "filed": f["filed"], "accn": f["accn"],
                                 "logged_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                 "engine": freeze["engine_label"], **got})
            seen.add(f["accn"])
            added += 1
        if i % 100 == 0:
            print(f"{i}/{len(companies)} companies checked", file=sys.stderr)
    print(f"{added} new forecasts; skipped {skipped or 'none'}")
    if a.limit:
        return 0
    forward.write(LOG, log)
    s = forward.summary(log, freeze)
    s["universe"] = len(companies)
    s["checked_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    OUT.write_text(json.dumps(s, indent=1) + "\n")
    print(f"{s['forecasts']} forecasts logged for {s['companies']} companies -> {LOG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
