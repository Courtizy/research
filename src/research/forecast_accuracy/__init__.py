"""Study 1: how accurate are mechanical forecasts built from filings, and are the
Valuation Model's ranges honest?

Layers, each a pure function of its inputs (no network, no file I/O):
  panel     one company's facts -> forecast origins (one per 10-K) and what came true
  methods   the forecasts each origin makes: naive baselines and the model's own
  metrics   errors, bias, skill against the naive forecast, range coverage, tests
Fetching and writing live in scripts/run_forecast_accuracy.py.
"""
