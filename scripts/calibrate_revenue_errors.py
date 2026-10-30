"""Write the calibrated revenue-error table for the Valuation Model from Study 1's panels.

    python scripts/run_forecast_accuracy.py      # first, so data/forecast_accuracy/panels exists
    python scripts/calibrate_revenue_errors.py   # -> site/data/calibration/revenue_errors.json, sector_growth.json

Copy both to the valuation repo's configs/public/calibration/. The errors are measured around the
blended forecast (no change, the model's fade, the sector), the Valuation Model's base case. Re-run once a year as new
10-Ks report the actuals.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from research.forecast_accuracy import calibration, study
from research.forecast_accuracy.metrics import division

ROOT = Path(__file__).resolve().parents[1]
PANELS = ROOT / "data" / "forecast_accuracy" / "panels"
OUT = ROOT / "site" / "data" / "calibration" / "revenue_errors.json"
SECTOR_OUT = OUT.parent / "sector_growth.json"


def _int_keys(d: dict) -> dict:
    return {int(k) if isinstance(k, str) and k.isdigit() else k: v for k, v in d.items()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--center", default="blend", help="forecast the errors are measured around")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)
    panels = [json.loads(f.read_text(), object_hook=_int_keys) for f in sorted(PANELS.glob("CIK*.json"))]
    if not panels:
        print("no panels: run scripts/run_forecast_accuracy.py first", file=sys.stderr)
        return 1
    panels = [p for p in panels if division(p.get("sic")) != "Finance"]
    study.add_sector_forecasts(panels)
    calibration.add_blend(panels)
    errors = calibration.scaled_errors(panels, args.center)
    tested = calibration.tested_coverage(calibration.scaled_errors(panels, args.center, with_dates=True))
    doc = calibration.table(errors, center=args.center, as_of=date.today().isoformat(), tested=tested,
                            source=f"Courtizy/research Study 1 panels: {len(panels)} companies, SEC filings")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(doc, indent=1) + "\n")
    print(f"{sum(len(v) for v in errors.values()):,} errors -> {args.out}")
    sectors = {"what": "Median three-year revenue CAGR of large US filers by SIC division and base calendar year",
               "source": doc["source"], "as_of": doc["as_of"], "divisions": calibration.sector_growth(panels)}
    SECTOR_OUT.write_text(json.dumps(sectors, indent=1) + "\n")
    print(f"sector growth -> {SECTOR_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
