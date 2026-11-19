"""Where a published result came from: the engine it scored, the run that wrote it, and where to get it.

Pure functions, no I/O: the run script passes in the environment, the notebook passes in the results file
and the ENGINE pin.
"""
from __future__ import annotations

import re

REPO = "https://github.com/Courtizy/research"
ENGINE_REPO = "https://github.com/Courtizy/valuation"


def run_info(env: dict) -> dict:
    """The run that wrote a results file. In GitHub Actions: its id and link; anywhere else: "local"."""
    run_id, repo = env.get("GITHUB_RUN_ID"), env.get("GITHUB_REPOSITORY")
    if run_id and repo:
        server = env.get("GITHUB_SERVER_URL", "https://github.com")
        return {"id": run_id, "url": f"{server}/{repo}/actions/runs/{run_id}"}
    return {"id": "local", "url": None}


def engine_commit(engine: str) -> str | None:
    """The short commit in an engine label like "valuation 0.9.0 @ 34e3852"."""
    m = re.search(r"@\s*([0-9a-f]{7,40})\b", engine or "")
    return m.group(1) if m else None


def describe(results: dict, engine_pin: str, results_path: str) -> list[tuple[str, str]]:
    """(label, markdown) rows for the notebook's provenance table. Raises if the results don't name the
    engine commit pinned in ENGINE: then the page would describe an engine the numbers didn't come from."""
    commit = engine_commit(results.get("engine", ""))
    if not commit or not engine_pin.strip().startswith(commit):
        raise ValueError(f"results name engine {results.get('engine')!r} but ENGINE pins {engine_pin.strip()[:7]}")
    run = results.get("run")
    run_md = (f"[{run['id']}]({run['url']})" if run and run.get("url")
              else f"recorded in the [results file's history]({REPO}/commits/main/{results_path})")
    return [
        ("Study version", f"{results.get('study')} v{results.get('version')}"),
        ("Data as of", str(results.get("as_of"))),
        ("Engine scored", f"{results['engine'].split(' @')[0]} at commit "
                          f"[`{commit}`]({ENGINE_REPO}/tree/{engine_pin.strip()}), pinned in `ENGINE`"),
        ("Run that wrote the results", run_md),
        ("Results file", f"[`{results_path}`]({REPO}/blob/main/{results_path})"),
    ]
