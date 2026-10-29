# Research & Analysis

*What does the evidence actually say?* Part of **[Decision Models](https://courtizy.github.io/)** by Jason C. Courtoy.

**[Read the studies](https://courtizy.github.io/research/)**

The models answer one question each. These studies test them, and the questions around them, on real public data. Each one states its question and hypotheses before looking, publishes its code and sources, reports how sure it is, and ends in a one-page memo for a decision-maker.

| # | Study | Question | Status |
|---|---|---|---|
| 01 | [Forecast Accuracy](https://courtizy.github.io/research/forecast-accuracy/) | How far should you trust the first five years of a DCF? | In development |
| 02 | Valuation Drivers | What drives valuation multiples across industries? | Planned |

## How it's built

The studies run on the **Valuation Model's tested engine** ([Courtizy/valuation](https://github.com/Courtizy/valuation)), pinned to the commit in `ENGINE`. They don't re-implement statement normalization or the DCF; they call it, so a study's result is also a test of the model.

| Folder | Purpose |
|---|---|
| `src/research/<study>/` | The study: pure functions, no network or file I/O |
| `scripts/run_<study>.py` | Fetches public data (cached in `data/`, gitignored), runs the study, writes `site/data/<study>.json` |
| `scripts/export_site.py` | Copies `brand/` into the site |
| `site/` | Static GitHub Pages site. Pages display the JSON only; no numbers are typed by hand |
| `tests/` | Offline tests on synthetic companies with known answers |

```bash
scripts/setup_engine.sh                                  # the Valuation engine at the pinned commit
pip install -e ".[dev]"
pytest -q
export SEC_USER_AGENT="Your Name you@example.com"        # the SEC requires contact details
python scripts/run_forecast_accuracy.py                  # about 1–2 hours for the full universe; resumes if stopped
python scripts/export_site.py
python -m http.server -d site 8000
```

## Data and licensing

Only public data. Study 01 uses SEC EDGAR XBRL company facts (US government data), fetched with a contact User-Agent within the SEC's fair-access limit. Downloads stay in `data/` and are never committed; only aggregate results are published.

Personal project · public data only · not investment advice · not endorsed by DoD or the U.S. Air Force.
