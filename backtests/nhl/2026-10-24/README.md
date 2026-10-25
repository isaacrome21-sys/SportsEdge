# NHL overnight backtest — 2026-10-24 (#2447)

**Historical only.** Does not touch the frozen Oct 8 – Nov 30 2026 NHL evaluation window, its ledger or verdict. No model math, thresholds or promotion changed.

- Source: `flancast90/sportsbookreview-scraper@1a820e50`, `data/nhl_archive_10Y.json`, git blob `9dd97a30…` (verified). Fetched via `git` (raw HTTPS blocked by session proxy). Calendar-date clock, unknown book, indicative not admitted.
- PIT features from strictly earlier dates; leakage check: 0 violations.
- Walk-forward by season; holdout = 2021-22 (n≈1.3–1.4k per market). One run, no tuning.
- Model A `FROZEN_COEF_PIT`: frozen v1 coefficients on PIT GF/GA (static 2025-26 priors are future data; no shots → shot_share 0.5).
- Model B `WF_POISSON`: same features, Poisson GLM refit on prior seasons only.

| Market | Model | n | Brier model / close | LogLoss model / close | EV≥2% bets | ROI | mean CLV | Verdict |
|---|---|---:|---|---|---:|---:|---:|---|
| Moneyline | A | 1390 | 0.2398 / 0.2257 | 0.673 / 0.643 | 1034 | −11.7% | −0.003 | LOSES_TO_CLOSE |
| Moneyline | B | 1390 | 0.2332 / 0.2257 | 0.659 / 0.643 | 860 | −10.0% | +0.001 | LOSES_TO_CLOSE |
| Totals | A | 1330 | 0.2585 / 0.2491 | 0.710 / 0.692 | 1006 | −9.0% | +0.002 | LOSES_TO_CLOSE |
| Totals | B | 1330 | 0.2493 / 0.2491 | 0.6919 / 0.6917 | 664 | +6.9% | +0.012 | LOSES_TO_CLOSE |
| Puck line | A | 1388 | 0.2548 / 0.2380 | 0.707 / 0.669 | 1339 | −5.1% | n/a | LOSES_TO_CLOSE |
| Puck line | B | 1388 | 0.2462 / 0.2380 | 0.687 / 0.669 | 1138 | −3.2% | n/a | LOSES_TO_CLOSE |

Calibration (slope/intercept/ECE), per-season folds and pooled dev in `results.json`. Totals-B holdout ROI +6.9% is noise-level (dev pooled +1.7%) on a one-sided totals price with an assumed 4.5% overround — not evidence of edge.

Rerun: `python backtests/nhl/2026-10-24/backtest_nhl.py --source <nhl_archive_10Y.json>`
