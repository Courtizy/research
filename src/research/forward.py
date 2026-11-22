"""The forward scoreboard: forecasts logged as companies file, scored as later 10-Ks report what happened.

This is the only fully clean test. The engine and its calibration tables were frozen on a stated day
(forward/FREEZE.json); every 10-K filed after it, by a company in Study 01's or the held-out sample, gets the
Valuation Model's default base case and calibrated 80% and 90% ranges for one to five years out, appended
to forward/forecasts.jsonl. Each record carries the SHA-256 of the one before it, so the log can only grow:
editing or dropping an earlier forecast breaks every hash after it. Git history dates each append.

Pure functions; scripts/forward_log.py does the fetching and calls the engine.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from statistics import median

HORIZONS = (1, 2, 3, 4, 5)
MATCH_DAYS = 25            # a target fiscal year's end may drift this much (52/53-week years)


def new_10ks(submissions: dict, since: str, seen: set[str]) -> list[dict]:
    """Original 10-Ks in an SEC submissions document filed on or after `since` and not already logged
    (by accession number), oldest first."""
    r = (submissions.get("filings") or {}).get("recent") or {}
    rows = zip(r.get("form", []), r.get("filingDate", []), r.get("accessionNumber", []), r.get("reportDate", []))
    out = [{"filed": d, "accn": a, "report_date": p} for f, d, a, p in rows
           if f == "10-K" and d >= since and a not in seen]
    return sorted(out, key=lambda x: (x["filed"], x["accn"]))


def _digest(rec: dict) -> str:
    body = {k: v for k, v in rec.items() if k != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def append(log: list[dict], rec: dict) -> dict:
    """Chain a new record onto the log and return it."""
    rec = {**rec, "prev": log[-1]["sha256"] if log else None}
    rec["sha256"] = _digest(rec)
    log.append(rec)
    return rec


def verify(log: list[dict]) -> bool:
    prev = None
    for rec in log:
        if rec.get("prev") != prev or rec.get("sha256") != _digest(rec):
            return False
        prev = rec["sha256"]
    return True


def read(path) -> list[dict]:
    from pathlib import Path
    p = Path(path)
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()] if p.exists() else []


def write(path, log: list[dict]) -> None:
    from pathlib import Path
    Path(path).write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in log))


def _target(base_end: str, h: int) -> date:
    d = date.fromisoformat(base_end)
    return date(d.year + h, d.month, 28) if (d.month, d.day) == (2, 29) else d.replace(year=d.year + h)


def scored(log: list[dict]) -> list[dict]:
    """One row per forecast and horizon whose actual has since been reported: the actual is the base-year
    revenue of the company's later logged 10-K whose fiscal year ends h years on (first reported, as in the studies)."""
    by_cik: dict[str, list[dict]] = {}
    for r in log:
        by_cik.setdefault(r["cik"], []).append(r)
    out = []
    for rs in by_cik.values():
        for r in rs:
            for h in HORIZONS:
                t = _target(r["base_end"], h)
                hit = next((x for x in rs if x["filed"] > r["filed"]
                            and abs((date.fromisoformat(x["base_end"]) - t).days) <= MATCH_DAYS), None)
                if not hit or str(h) not in r["forecast"]:
                    continue
                a, f = hit["base_revenue"], r["forecast"][str(h)]
                lo80, hi80 = r["range"]["80"][str(h)]
                lo90, hi90 = r["range"]["90"][str(h)]
                out.append({"cik": r["cik"], "h": h, "filed": r["filed"], "actual_filed": hit["filed"],
                            "miss": abs(a / f - 1), "in80": lo80 <= a <= hi80, "in90": lo90 <= a <= hi90,
                            "beats_no_change": abs(a / f - 1) < abs(a / r["base_revenue"] - 1)})
    return out


def summary(log: list[dict], freeze: dict) -> dict:
    """What the site shows: what's been logged, and by horizon whatever has been scored so far."""
    rows = scored(log)
    by_h = []
    for h in HORIZONS:
        rs = [r for r in rows if r["h"] == h]
        if rs:
            by_h.append({"h": h, "n": len(rs), "companies": len({r["cik"] for r in rs}),
                         "median_miss": median(r["miss"] for r in rs),
                         "inside_80": sum(r["in80"] for r in rs) / len(rs),
                         "inside_90": sum(r["in90"] for r in rs) / len(rs),
                         "beats_no_change": sum(r["beats_no_change"] for r in rs) / len(rs)})
    filed = [r["filed"] for r in log]
    return {"study": "forward-scoreboard", "frozen_on": freeze["frozen_on"], "engine": freeze["engine_label"],
            "log_intact": verify(log), "forecasts": len(log), "companies": len({r["cik"] for r in log}),
            "first_filed": min(filed, default=None), "last_filed": max(filed, default=None),
            "last_hash": log[-1]["sha256"] if log else None, "scored": by_h}
