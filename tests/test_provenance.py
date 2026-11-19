"""The study page says which engine and run produced its numbers; these keep that statement true."""
import json
from pathlib import Path

import pytest

from research import provenance

ROOT = Path(__file__).resolve().parents[1]
PUBLISHED = "site/data/forecast_accuracy.json"


def test_published_results_name_the_pinned_engine():
    # The page prints the engine from the results file and links the ENGINE commit; they must be the same engine.
    results = json.loads((ROOT / PUBLISHED).read_text())
    rows = dict(provenance.describe(results, (ROOT / "ENGINE").read_text(), PUBLISHED))
    pin = (ROOT / "ENGINE").read_text().strip()
    assert provenance.engine_commit(results["engine"]) == pin[:7]
    assert pin in rows["Engine scored"] and rows["Data as of"] == results["as_of"]


def test_mismatched_engine_is_refused():
    with pytest.raises(ValueError):
        provenance.describe({"engine": "valuation 0.9.0 @ 34e3852"}, "deadbee" + "0" * 33, PUBLISHED)
    with pytest.raises(ValueError):
        provenance.describe({"engine": "valuation 0.9.0"}, "34e3852", PUBLISHED)


def test_run_info_from_actions_and_locally():
    env = {"GITHUB_RUN_ID": "41097931174", "GITHUB_REPOSITORY": "Courtizy/research"}
    assert provenance.run_info(env) == {"id": "41097931174",
                                        "url": "https://github.com/Courtizy/research/actions/runs/41097931174"}
    assert provenance.run_info({}) == {"id": "local", "url": None}


def test_run_row_links_the_run_when_recorded_else_the_file_history():
    base = {"study": "forecast-accuracy", "version": 2, "as_of": "2026-10-30", "engine": "valuation 0.9.0 @ 34e3852"}
    rows = dict(provenance.describe({**base, "run": provenance.run_info(
        {"GITHUB_RUN_ID": "1", "GITHUB_REPOSITORY": "Courtizy/research"})}, "34e3852", PUBLISHED))
    assert "actions/runs/1" in rows["Run that wrote the results"]
    assert "commits/main/" + PUBLISHED in dict(provenance.describe(base, "34e3852", PUBLISHED))["Run that wrote the results"]
