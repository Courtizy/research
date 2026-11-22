"""The held-out test on synthetic companies: a separate sample, ranges calibrated only on Study 01's."""
import copy
import random

import pytest

from synthetic import company
from research.forecast_accuracy import calibration, held_out, ranges, study, universe
from research.forecast_accuracy.panel import company_panel


def _panels(n, seed, cik0=0, sics=("3720", "7372")):
    rng = random.Random(seed)
    out = []
    for i in range(n):
        g, r, rev = rng.uniform(0.0, 0.12), 100.0, {}
        for y in range(2008, 2024):
            rev[y] = r
            r *= 1 + g + rng.gauss(0, 0.06)
        out.append(company_panel(company(rev, cik=f"{cik0 + i:010d}", sic=sics[i % len(sics)])))
    return out


def test_held_out_draw_is_fixed_by_rule_and_skips_study_01():
    frames = {2011: [[k, f"Co {k}", None, None, v] for k, v in
                     [(1, 3e8), (2, 5e8), (3, 9e8), (4, 2e9), (5, 1e8), (6, 1e9), (7, 2.5e8)]]}
    picked = universe.select_held_out(frames, exclude={"0000000002"}, per_cohort=10)
    assert {c["cik"] for c in picked} == {"0000000001", "0000000003", "0000000007"}   # in band, $1B excluded
    few = universe.select_held_out(frames, exclude=set(), per_cohort=2)
    again = universe.select_held_out({2011: list(reversed(frames[2011]))}, exclude=set(), per_cohort=2)
    assert few == again and len(few) == 2


def test_holm():
    assert held_out.holm([0.01, 0.04, 0.03, None]) == pytest.approx([0.03, 0.06, 0.06, None])
    assert held_out.holm([0.5, 0.9]) == pytest.approx([1.0, 1.0])


def test_baselines():
    p = _panels(1, 1)
    held_out.add_baselines(p)
    o = next(o for o in p[0]["origins"] if o["g3"] is not None)
    assert o["revenue"]["shrink"][2] == pytest.approx(o["r0"] * (1 + 0.5 * o["g3"]) ** 2)
    assert "drift" in o["revenue"]


def test_held_out_ranges_use_only_the_calibration_companies():
    """Wrecking the held-out companies' actuals changes their hits but never the range they're scored with."""
    held, cal = _panels(20, 5, cik0=100), _panels(30, 3)
    for ps in (held, cal):
        study.add_sector_forecasts(ps)
        calibration.add_blend(ps)
    wrecked = copy.deepcopy(held)
    for p in wrecked:
        for o in p["origins"]:
            o["actual"] = {h: a * 3 for h, a in o["actual"].items()}
    a = ranges.range_hits(held, min_calibration=50, calibration=cal)
    b = ranges.range_hits(wrecked, min_calibration=50, calibration=cal)
    assert a and [(r["cik"], r["h"], r["n_calibration"], r["reach"]) for r in a] == \
        [(r["cik"], r["h"], r["n_calibration"], r["reach"]) for r in b]
    assert all("hit_unscaled" in r for r in a)


def test_held_out_runs_end_to_end():
    res = held_out.run(_panels(24, 5, cik0=100, sics=("3720", "7372", "6021")), _panels(30, 3), engine="t",
                       as_of="x", universe_size=24, preregistration="abc", min_calibration=50)
    assert res["sample"]["excluded_finance"] == 8 and res["preregistration"] == "abc"
    assert [p["id"] for p in res["primary"]] == ["P1", "P2", "P3"]
    assert res["confirms"] == all(p["passed"] for p in res["primary"])
    assert {a["method"] for a in res["accuracy"]} >= {"blend", "shrink", "drift"}
    for r in res["ranges"]:
        assert 0 <= r["fixed"]["share"] <= 1 and r["fixed_half_width"] > 0
    assert res["headline"]["lead"] and len(res["headline"]["kpis"]) == 3
