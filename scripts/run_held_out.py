"""The held-out test of Study 01: the same methods on companies the study never looked at.

    export SEC_USER_AGENT="Your Name you@example.com"
    python scripts/run_held_out.py              # Study 01's panels (for the ranges' calibration), then the held-out sample
    python scripts/run_held_out.py --limit 3    # a plumbing check; not published

The plan, written before the run, is docs/preregistration/forecast-accuracy-held-out.md; the results file
names the commit that added it. Downloads go to data/held_out/ (gitignored). The result is site/data/held_out.json.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_forecast_accuracy as s01  # noqa: E402

from research import provenance  # noqa: E402
from research.forecast_accuracy import held_out, universe  # noqa: E402

ROOT = s01.ROOT
DATA = ROOT / "data" / "held_out"
OUT = ROOT / "site" / "data" / "held_out.json"
PLAN = "docs/preregistration/forecast-accuracy-held-out.md"


def plan_commit() -> str:
    """The commit that first added the written plan: the record that it came before the run."""
    out = subprocess.run(["git", "-C", str(ROOT), "log", "--diff-filter=A", "--format=%H", "--", PLAN],
                         capture_output=True, text=True, check=True).stdout.split()
    if not out:
        raise SystemExit(f"{PLAN} isn't committed: write the plan down before running")
    return out[-1]


def build_held_out(sec, study01: list[dict]) -> list[dict]:
    path = DATA / "universe.json"
    if path.exists():
        return json.loads(path.read_text())
    chosen = universe.select_held_out(s01.revenue_frames(sec), exclude={c["cik"] for c in study01})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(chosen, indent=1))
    return chosen


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--limit", type=int, help="only the first N held-out companies (plumbing check)")
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args(argv)

    plan = plan_commit()
    sec = s01.sec_adapter()
    study01 = s01.build_universe(sec)
    print(f"Study 01: {len(study01)} companies (the ranges' calibration)", file=sys.stderr)
    cal = s01.load_panels(sec, study01)
    chosen = build_held_out(sec, study01)
    assert not {c["cik"] for c in chosen} & {c["cik"] for c in study01}, "held-out sample overlaps Study 01"
    chosen = chosen[: a.limit]
    print(f"held out: {len(chosen)} companies", file=sys.stderr)
    panels = s01.load_panels(sec, chosen, DATA)
    result = held_out.run(panels, cal, engine=s01.engine_version(), as_of=date.today().isoformat(),
                          universe_size=len(chosen), preregistration=plan)
    result["run"] = provenance.run_info(dict(os.environ))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(result, indent=1))
    s = result["sample"]
    print(f"{s['companies_scored']} held-out companies, {s['observations']} observations -> {a.out}")
    for p in result["primary"]:
        print(f"  {p['id']} {'pass' if p['passed'] else 'FAIL'}: {p['test']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
