"""Study 1 on synthetic companies: known answers, no network."""
import math
import random

import pytest

from synthetic import company
from research.forecast_accuracy import methods, metrics, study, universe
from research.forecast_accuracy.panel import company_panel, origins

from valuation._core.projection import project


GROWING = {y: 100 * 1.10 ** (y - 2010) for y in range(2010, 2021)}


def test_origins_are_10k_filing_dates():
    assert origins(company(GROWING))[:2] == ["2011-02-15", "2012-02-15"]


def test_fade_path_matches_engine():
    base = {"revenue": 100.0}
    years = project(base, {"revenue": {"method": "fade", "g0": 0.12, "g_terminal": 0.025, "fade_years": 10}}, 5)["years"]
    ours = methods.fade_path(100.0, 0.12, 5)
    assert [round(y["revenue"], 6) for y in years] == [round(v, 6) for v in ours]


def test_triangular_quantiles():
    assert methods.tri_quantile(0.5, -1, 0, 1) == pytest.approx(0)
    assert methods.tri_quantile(0.0, 0.02, 0.05, 0.08) == pytest.approx(0.02)
    assert methods.tri_quantile(1.0, 0.02, 0.05, 0.08) == pytest.approx(0.08)


def test_band_brackets_model_and_matches_simulation():
    fc = methods.revenue_forecasts([80.0, 90.0, 100.0], 0.08)["forecasts"]
    for h in methods.HORIZONS:
        assert fc["model_p10"][h] < fc["model"][h] < fc["model_p90"][h]
    # the exact quantile equals a large seeded simulation of the same triangular draw
    gen = random.Random(7)
    sims = sorted(methods.fade_path(100.0, gen.triangular(0.05, 0.11, 0.08), 3)[-1] for _ in range(40000))
    assert fc["model_p90"][3] == pytest.approx(sims[int(0.9 * len(sims))], rel=2e-3)


def test_steady_grower_is_forecast_exactly_by_its_own_history():
    p = company_panel(company(GROWING))
    o = next(o for o in p["origins"] if o["n_history"] >= 4)
    for h, a in o["actual"].items():
        assert o["revenue"]["hist3"][h] == pytest.approx(a)
        assert o["revenue"]["naive"][h] < a


def test_no_lookahead():
    """Every origin's forecasts are identical when the facts filed after it never existed."""
    raw = company(GROWING, restate={(2015, 2014): 999.0})
    full = {o["origin"]: o for o in company_panel(raw)["origins"]}
    for d, o in full.items():
        cut = {**raw, "facts": [f for f in raw["facts"] if f["filed"] <= d]}
        early = next(x for x in company_panel(cut)["origins"] if x["origin"] == d)
        assert early["revenue"] == o["revenue"] and early["history"] == o["history"]


def test_actuals_are_first_reported_not_restated():
    # the FY2015 10-K restates FY2014; the forecast made in early 2014 is scored on FY2014 as first reported
    raw = company(GROWING, restate={(2015, 2014): 999.0})
    o = next(o for o in company_panel(raw)["origins"] if o["base_end"] == "2013-12-31")
    assert o["actual"][1] == pytest.approx(GROWING[2014])


def test_engine_failure_on_bad_filed_data_is_counted_not_fatal():
    # a negative revenue fact (bad tagging) makes the engine's CAGR complex
    raw = company(dict(zip(range(2010, 2017), [100, 110, 120, -5, 130, 140, 150])), cik="0000000007", name="Bad")
    p = company_panel(raw)
    assert p["engine_errors"] >= 1 and all(r["r0"] > 0 for r in p["origins"])


def test_clustered_se_one_cluster_per_obs_matches_plain_se():
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    r = metrics.clustered_mean(xs, list("abcde"))
    plain = math.sqrt(sum((x - 3) ** 2 for x in xs) / 5 * 5 / 4) / math.sqrt(5)   # n/(n-1) correction
    assert r["mean"] == 3.0 and r["se"] == pytest.approx(plain)


def test_universe_keeps_firms_that_later_disappear():
    frames = {2011: [[1, "Gone Inc", None, None, 5e9], [2, "Still Here", None, None, 4e9]],
              2019: [[2, "Still Here", None, None, 6e9], [3, "New Co", None, None, 2e9], [4, "Tiny", None, None, 1e8]]}
    picked = {c["cik"]: c["cohorts"] for c in universe.select(frames)}
    assert picked == {"0000000001": [2011], "0000000002": [2011, 2019], "0000000003": [2019]}


def _random_panels(n=30, seed=3):
    rng = random.Random(seed)
    panels = []
    for i in range(n):
        g, r, rev = rng.uniform(0.0, 0.12), 100.0, {}
        for y in range(2008, 2024):
            rev[y] = r
            r *= 1 + g + rng.gauss(0, 0.06)
        panels.append(company_panel(company(rev, cik=f"{i:010d}", sic=["3720", "7372", "6021"][i % 3])))
    return panels


def test_study_runs_end_to_end_and_excludes_finance():
    res = study.run(_random_panels(), engine="test", as_of="2026-10-29", universe_size=30)
    s = res["sample"]
    assert s["excluded_finance"] == 10 and s["companies_scored"] == 20
    assert {a["method"] for a in res["accuracy"]} == {"naive", "hist3", "sector", "model"}
    naive = [a for a in res["accuracy"] if a["method"] == "naive"]
    assert all(a["skill_vs_naive"] == pytest.approx(0) for a in naive)
    assert all(0 <= c["coverage"] <= 1 for c in res["coverage"])
    assert res["robustness"]["no_large_moves"]["n"] <= s["observations"]
    assert set(res["memo"]) == {"practice", "valuation_model"}


def test_study_is_deterministic():
    a = study.run(_random_panels(), engine="t", as_of="x", universe_size=30)
    b = study.run(_random_panels(), engine="t", as_of="x", universe_size=30)
    assert a == b
