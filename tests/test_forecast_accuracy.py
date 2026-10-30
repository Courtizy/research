"""Study 1 on synthetic companies: known answers, no network."""
import copy
import math
import random
import statistics

import pytest

from synthetic import company
from research.forecast_accuracy import methods, metrics, study, universe
from research.forecast_accuracy.metrics import division
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


def test_engine_failure_on_bad_filed_data_is_counted_not_fatal(monkeypatch):
    # engines before 0.7.1 crashed on a negative revenue fact (the CAGR went complex); simulate that
    # crash on one origin so the test holds whatever engine is pinned
    from research.forecast_accuracy import panel
    real = panel.build_detail

    def flaky(canonical, as_of):
        if as_of.startswith("2014"):
            raise TypeError("'<' not supported between instances of 'complex' and 'int'")
        return real(canonical, as_of)

    monkeypatch.setattr(panel, "build_detail", flaky)
    raw = company(dict(zip(range(2010, 2017), [100, 110, 120, -5, 130, 140, 150])), cik="0000000007", name="Bad")
    p = company_panel(raw)
    assert p["engine_errors"] == 1 and all(r["r0"] > 0 for r in p["origins"])


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
    res = study.run(_random_panels(), engine="test", as_of="2026-10-29", universe_size=30, min_calibration=50)
    s = res["sample"]
    assert s["excluded_finance"] == 10 and s["companies_scored"] == 20
    assert {a["method"] for a in res["accuracy"]} == {"naive", "hist3", "sector", "model", "blend"}
    naive = [a for a in res["accuracy"] if a["method"] == "naive"]
    assert all(a["skill_vs_naive"] == pytest.approx(0) for a in naive)
    assert all(0 <= c["coverage"] <= 1 for c in res["coverage"])
    assert res["robustness"]["no_large_moves"]["n"] <= s["observations"]
    assert set(res["memo"]) == {"practice", "valuation_model"}
    assert any("80% range" in k["label"] for k in res["headline"]["kpis"])


def test_study_is_deterministic():
    a = study.run(_random_panels(), engine="t", as_of="x", universe_size=30)
    b = study.run(_random_panels(), engine="t", as_of="x", universe_size=30)
    assert a == b


def test_calibration_table_is_monotone_and_scaled():
    from research.forecast_accuracy import calibration
    assert calibration.revenue_vol([100, 110, 121, 133.1]) == pytest.approx(0)
    assert calibration.revenue_vol([100]) == calibration.DEFAULT_VOL
    errs = calibration.scaled_errors(_random_panels())
    assert all(errs[h] for h in (1, 3, 5))
    t = calibration.table(errs, center="model", source="test", as_of="x")
    for q in t["quantiles"].values():
        assert q == sorted(q) and len(q) == len(t["p"])
    assert 0.05 in t["p"] and 0.95 in t["p"] and 0.025 in t["p"]


def test_blend_is_the_geometric_mean_of_flat_model_and_sector():
    from research.forecast_accuracy import calibration
    panels = _random_panels()
    study.add_sector_forecasts(panels)
    calibration.add_blend(panels)
    o = next(o for p in panels for o in p["origins"] if o["revenue"].get("sector") and o["revenue"]["blend"])
    h = min(o["revenue"]["blend"])
    want = (o["r0"] * o["revenue"]["model"][h] * o["revenue"]["sector"][h]) ** (1 / 3)
    assert o["revenue"]["blend"][h] == pytest.approx(want)
    sg = calibration.sector_growth(panels, min_peers=1)
    assert "Finance" not in sg and all(v["n"] >= 1 for d in sg.values() for v in d.values())


def test_tested_coverage_is_near_nominal_for_stable_errors():
    from research.forecast_accuracy import calibration
    rng = random.Random(5)
    rows = {h: [{"year": y, "origin": f"{y + 1}-03-01", "known": f"{y + 1 + h}-03-01", "z": rng.gauss(0, 1)}
                for y in range(2005, 2025) for _ in range(60)] for h in (1, 3)}
    t = calibration.tested_coverage(rows, min_calibration=100)
    for lvl, nominal in (("80", 0.8), ("90", 0.9)):
        for h in ("1", "3"):
            assert abs(t["levels"][lvl][h]["coverage"] - nominal) < 0.04


def test_ranges_are_scored_on_the_same_observations():
    res = study.run(_random_panels(), engine="t", as_of="x", universe_size=30, min_calibration=50)
    for c in res["ranges"]:
        assert 0 <= c["simulated"]["share"] <= 1 and c["simulated"]["n"] == c["n"]
        assert set(c["calibrated"]) == {"80", "90", "95"}
        cal = c["calibrated"]
        assert cal["80"]["share"] <= cal["90"]["share"] <= cal["95"]["share"]
        assert cal["80"]["above"] < cal["95"]["above"]
    from research.forecast_accuracy import ranges
    assert [g["group"] for g in res["ranges_by_volatility"]] == list(ranges.VOL_GROUPS)
    assert res["sample"]["range_test"]["observations"] > 0

def _staggered_panels(n=30, seed=3):
    """Like _random_panels, but companies file their 10-Ks on different days, so fiscal years that end
    together become public weeks or months apart (the case a calendar-year cutoff gets wrong)."""
    rng = random.Random(seed)
    panels = []
    for i in range(n):
        g, r, rev = rng.uniform(0.0, 0.12), 100.0, {}
        for y in range(2008, 2024):
            rev[y] = r
            r *= 1 + g + rng.gauss(0, 0.06)
        panels.append(company_panel(company(rev, cik=f"{i:010d}", sic=["3720", "7372"][i % 2],
                                            filed_month_day=["02-10", "03-15", "05-20"][i % 3])))
    return panels


def _wreck_after(panels, cutoff):
    """The same panels with every fact first filed after `cutoff` replaced by nonsense: peers' growth from
    later 10-Ks, and actuals reported by later 10-Ks."""
    out = copy.deepcopy(panels)
    for p in out:
        for o in p["origins"]:
            if o["origin"] > cutoff:
                o["g3"] = 5.0
            o["actual"] = {h: a * 10 if o["actual_origin"][h] > cutoff else a for h, a in o["actual"].items()}
    return out


def test_sector_forecast_ignores_peers_filed_later():
    """A peer's later 10-K can't change an earlier sector forecast (point in time across companies)."""
    panels = _staggered_panels()
    study.add_sector_forecasts(panels)
    for cutoff in ("2014-02-10", "2016-03-15", "2019-02-28"):
        wrecked = _wreck_after(panels, cutoff)
        study.add_sector_forecasts(wrecked)
        for p, w in zip(panels, wrecked):
            for o, ow in zip(p["origins"], w["origins"]):
                if o["origin"] <= cutoff:
                    assert ow["revenue"].get("sector") == o["revenue"].get("sector"), (p["cik"], o["origin"])
    assert any(o["revenue"].get("sector") for p in panels for o in p["origins"])


def test_sector_forecast_waits_for_a_peer_filing_on_the_same_fiscal_year():
    """February filers don't see a March filer's year until it is filed, even though both years ended in December."""
    panels = _staggered_panels()
    feb = next(p for p in panels if p["origins"][0]["origin"].endswith("02-10"))
    o = next(o for o in feb["origins"] if o["base_end"] == "2015-12-31")
    peers = [x for p in panels if p["cik"] != feb["cik"] and division(p["sic"]) == division(feb["sic"])
             for x in p["origins"] if x["origin"] <= o["origin"] and x["g3"] is not None]
    assert all(x["base_end"] <= "2015-12-31" for x in peers)
    latest = {}
    for p in panels:
        if p["cik"] != feb["cik"] and division(p["sic"]) == division(feb["sic"]):
            got = [x for x in p["origins"] if x["origin"] <= o["origin"] and x["g3"] is not None]
            if got:
                latest[p["cik"]] = got[-1]["g3"]
    study.add_sector_forecasts(panels)
    want = methods.sector_forecasts(o["r0"], statistics.median(latest.values()))
    assert o["revenue"]["sector"] == pytest.approx(want)


def test_range_hits_never_see_the_future():
    """A forecast's range is built only from errors whose actuals were filed by its own filing date:
    wrecking every actual filed later leaves the range (its width and calibration count) unchanged."""
    from research.forecast_accuracy import calibration, ranges
    panels = _staggered_panels()
    for cutoff in ("2016-02-10", "2017-03-15", "2019-05-20"):
        runs = []
        for ps in (panels, _wreck_after(panels, cutoff)):
            ps = copy.deepcopy(ps)
            study.add_sector_forecasts(ps)
            calibration.add_blend(ps)
            runs.append([(r["cik"], r["h"], r["origin"], r["n_calibration"], r["reach"])
                         for r in ranges.range_hits(ps, min_calibration=50) if r["origin"] <= cutoff])
        assert runs[0] and runs[0] == runs[1]


def test_known_quantiles_wait_for_the_filing_not_the_fiscal_year_end():
    from research.forecast_accuracy import calibration
    rows = [{"known": "2016-02-10", "z": 0.0}, {"known": "2016-05-20", "z": 1.0}]
    tests = [{"origin": "2016-03-15"}, {"origin": "2016-05-20"}, {"origin": "2016-01-01"}]
    (n1, _), (n2, _), (n0, q0) = calibration.known_quantiles(rows, tests)
    assert (n0, n1, n2) == (0, 1, 2) and q0 == {}


def test_blend_matches_the_engine():
    """The blend scored here is the engine's default base case: same path for the same inputs."""
    from valuation._core.projection import project
    g0, gs = 0.12, 0.04
    years = project({"revenue": 100.0}, {"revenue": {"method": "blend", "g0": g0, "g_terminal": 0.025,
                                                     "fade_years": 10, "sector_growth": gs}}, 5)["years"]
    fade = methods.fade_path(100.0, g0, 5)
    want = [(100.0 * f * 100.0 * (1 + gs) ** t) ** (1 / 3) for t, f in enumerate(fade, 1)]
    assert [y["revenue"] for y in years] == pytest.approx(want)
