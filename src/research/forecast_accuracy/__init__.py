"""Study 1: how accurate are mechanical forecasts built from filings, and are the
Valuation Model's ranges honest?

Layers, each a pure function of its inputs (no network, no file I/O):
  panel     one company's facts -> forecast origins (one per 10-K) and what came true
  methods   the forecasts each origin makes: naive baselines and the model's own
  metrics   errors, bias, skill against the naive forecast, range coverage, tests
  calibration  the blended forecast and ranges from past misses (and the tables the Valuation Model reads)
  ranges    both kinds of range scored out of sample, point in time
Fetching and writing live in scripts/run_forecast_accuracy.py.
"""
