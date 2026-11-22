"""The forward log: append-only, tamper-evident, scored only once later 10-Ks report the actuals."""
import copy

from research import forward

FREEZE = {"frozen_on": "2026-11-22", "engine_label": "valuation 0.10.1 @ 4313ce4"}


def _rec(cik, filed, base_end, r0, g=0.05):
    return {"cik": cik, "filed": filed, "accn": f"{cik}-{filed}", "base_end": base_end, "base_revenue": r0,
            "forecast": {str(h): r0 * (1 + g) ** h for h in forward.HORIZONS},
            "range": {lvl: {str(h): [r0 * (1 + g) ** h * (1 - w * h), r0 * (1 + g) ** h * (1 + w * h)]
                            for h in forward.HORIZONS} for lvl, w in (("80", 0.05), ("90", 0.08))}}


def test_new_10ks_skips_amendments_old_filings_and_logged_ones():
    sub = {"filings": {"recent": {"form": ["10-K", "10-Q", "10-K/A", "10-K", "10-K"],
                                  "filingDate": ["2027-02-20", "2027-05-01", "2027-03-01", "2026-02-20", "2027-12-01"],
                                  "accessionNumber": ["a1", "a2", "a3", "a4", "a5"],
                                  "reportDate": ["2026-12-31", "", "", "2025-12-31", "2027-09-30"]}}}
    got = forward.new_10ks(sub, "2026-11-22", seen={"a5"})
    assert [g["accn"] for g in got] == ["a1"]


def test_log_is_tamper_evident():
    log = []
    forward.append(log, _rec("1", "2027-02-20", "2026-12-31", 100.0))
    forward.append(log, _rec("1", "2028-02-20", "2027-12-31", 104.0))
    assert forward.verify(log)
    edited = copy.deepcopy(log)
    edited[0]["forecast"]["3"] *= 1.1
    assert not forward.verify(edited)
    assert not forward.verify(log[1:])            # dropping the first record breaks the chain


def test_scored_only_when_a_later_10k_reports_the_year():
    log = []
    forward.append(log, _rec("1", "2027-02-20", "2026-12-31", 100.0))
    assert forward.summary(log, FREEZE)["scored"] == []
    forward.append(log, _rec("1", "2028-02-21", "2027-12-31", 103.0))
    forward.append(log, _rec("2", "2028-03-01", "2027-12-31", 50.0))      # another company: no actual for "1"
    s = forward.summary(log, FREEZE)
    assert s["log_intact"] and s["forecasts"] == 3 and s["companies"] == 2
    (h1,) = s["scored"]
    assert h1["h"] == 1 and h1["n"] == 1 and h1["inside_80"] == 1.0
    assert abs(h1["median_miss"] - (1 - 103 / 105)) < 1e-12


def test_write_and_read_round_trip(tmp_path):
    log = []
    forward.append(log, _rec("1", "2027-02-20", "2026-12-31", 100.0))
    p = tmp_path / "f.jsonl"
    forward.write(p, log)
    assert forward.read(p) == log and forward.verify(forward.read(p))
