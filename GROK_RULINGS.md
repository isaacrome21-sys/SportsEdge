# GROK_RULINGS

## 2026-10-23i — CFB per-market candidate gate (delegated ruling)

Every CFB market — spread, total, moneyline, first/second halves, team totals,
and the t272 fallback composition — is blocked from candidate status until its
out-of-sample 2025 Brier beats the closing no-vig market with a confidence
interval (paired bootstrap 95% CI of mean(model Brier − market Brier) entirely
below 0).

* Implemented as a per-market gate (`sportsedge/sports/cfb/market_gate.py`)
  driven only by recorded backtest metrics in
  `docs/cfb_market_gate_metrics_20261023i.json`, written by
  `scripts/cfb_calibration/backtest_opponent_ratings.py` (fit 2024, score 2025).
* Pass/fail is computed from the recorded numbers; no stored flag can pass a
  market. Markets with no recorded metrics (halves, team totals, t272
  fallback) are blocked. Gates must never be hand-edited to pass.
* Blocked markets still show research numbers and raw values with status
  `WATCH_CFB_NOT_BETTER_THAN_MARKET` and a `NOT_BETTER_THAN_MARKET:…` reason,
  never as candidates.
* As recorded at ruling time, all three priced markets are blocked:
  spread CI [−0.00032, +0.00018], total [−0.0009, +0.00482], ML [+0.00353, +0.01675].

SCREEN / NOT_VALIDATED; play_allowed=false; research only.
