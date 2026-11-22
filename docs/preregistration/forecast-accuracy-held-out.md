# Forecast Accuracy: held-out test, written down before the run

*Committed before any held-out company was fetched or scored. The commit that adds this file is the record
of what was decided in advance; the results file names it.*

## Why
Study 01 picked the blend (the geometric mean of no change, faded growth and the sector's growth) after looking
at the same large-company filings it is scored on. Its ranges were already scored out of sample over time, but
the blend's gain over no change is an in-sample result. This test scores the same methods, unchanged, on
companies the study has never looked at.

## Sample
- **Source:** the SEC's XBRL frames for calendar years 2011, 2015 and 2019, across the same revenue tags as Study 01.
- **Band:** filers whose largest reported revenue that year was at least $250M and under $1B.
- **Never examined:** any company in Study 01's universe is removed first.
- **Draw:** in each cohort year, the 300 eligible filers with the lowest SHA-256 hash of their 10-digit CIK.
  The draw is fixed by the rule, so no one picks companies. The sample is the union across the three years.
- **Exclusions:** finance (SIC 60–67) is dropped, as in Study 01.

## Methods: frozen
Everything is the code and engine of Study 01 as merged: engine `valuation 0.9.0 @ 34e3852` (the `ENGINE` pin),
point-in-time origins at every 10-K, the same five forecasts and the same scoring. The sector leg of the blend is
the median three-year growth of the held-out sample's own peers in the same SIC division, filed on or before
each origin (the Study 01 rule, applied to the new sample). No parameter is re-fit on the held-out companies.

**Ranges.** Each held-out forecast's calibrated range comes from Study 01's errors only: the scaled errors of the
large-company blend whose actuals had been filed by the held-out forecast's own filing date. So the range is held
out by company and by time. As in Study 01, only forecasts from base year 2014 on are scored, and only when at
least 200 errors were known.

## Primary results: three years out, decided now
| # | Test | Confirms if |
|---|---|---|
| P1 | Blend vs no change, mean absolute log error, clustered by company | blend has less error and t ≥ 2 |
| P2 | Blend vs faded growth, same test on the same observations | blend has less error and t ≥ 2 |
| P3 | Share of outcomes inside the calibrated 80% range | between 75% and 85% |

The held-out test **confirms Study 01** if all three pass. It is reported as it comes out, including a failure.

## Secondary results
- The same comparisons at 1, 2, 4 and 5 years, with p-values Holm-adjusted across the five horizons (for P1 and P2).
- 90% range coverage; coverage by volatility tercile.
- **Baselines, shown beside the blend:**
  - *Shrinkage:* half the company's three-year growth, held flat (`g = 0.5 × g3`). Is the fade better than plain shrinkage?
  - *Fixed band:* a symmetric ±w band in log terms around the blend, with w at each horizon set to the median
    half-width of the calibrated 80% range on the same observations. Is the range's shape doing the work, or just its width?
- **In the notebook only:**
  - *Drift:* the company's median yearly growth over up to five years, held flat.
  - *Unscaled range:* quantiles of Study 01's raw log errors (no volatility scaling), known by each filing date.

## Running it
One full run in GitHub Actions (`held-out.yml`), on the commit after this one that adds the code. Runs limited
to a handful of companies to check the plumbing are allowed and are not published. If the full run exposes a
bug, the fix and the reason are recorded in the results file's commit and the run is repeated once.
