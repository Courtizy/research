"""Study 1b: score Study 1's forecasts again against the fixed Valuation Model.

    python scripts/run_forecast_accuracy.py   # first, so data/forecast_accuracy/panels exists
    python scripts/run_forecast_rescore.py    # -> site/data/forecast_accuracy_rescore.json

Reads the same point-in-time panels as Study 1, so before and after are scored on the same
companies, filing dates and actuals. Takes seconds; no network.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from research.forecast_accuracy import rescore

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_forecast_accuracy import DATA, ROOT, _int_keys, engine_version  # noqa: E402

OUT = ROOT / "site" / "data" / "forecast_accuracy_rescore.json"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args(argv)
    panels = [json.loads(f.read_text(), object_hook=_int_keys) for f in sorted((DATA / "panels").glob("CIK*.json"))]
    if not panels:
        print("no panels: run scripts/run_forecast_accuracy.py first", file=sys.stderr)
        return 1
    universe = len(json.loads((DATA / "universe.json").read_text()))
    res = rescore.run(panels, engine=engine_version(), as_of=date.today().isoformat(), universe_size=universe)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(res, indent=1))
    print(f"{res['sample']['observations']} observations, {res['sample']['range_test']['observations']} range tests -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
