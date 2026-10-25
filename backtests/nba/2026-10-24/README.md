# NBA overnight backtest — 2026-10-24 (#2447)

Reproduces and extends the Oct 21 negative screens. No model math, thresholds or promotion changed.

- Source: same SBR archive, `data/nba_archive_10Y.json`, blob `f5ba0d4f…` (verified). Calendar-date clock, indicative not admitted.
- **Reproduction:** Elo V2 8,877 games, margin RMSE 13.4522 vs market 12.7511, ML Brier 0.21755 vs 0.20670; totals V2 RMSE 18.9770 vs 18.0512 — identical to the published screens.
- Extension: point forecasts → probabilities (Normal, residual SD fit walk-forward on earlier seasons only). Leakage check: same-day outcome scramble on 62 games, 0 violations; totals inputs all strictly earlier dates.
- Holdout = 2021-22. One run. Uses the shared `backtests/nhl/2026-10-24/metrics.py`.

| Market | n | Brier model / close | LogLoss model / close | Cal slope | EV≥2% bets | ROI | mean CLV | Verdict |
|---|---:|---|---|---:|---:|---:|---:|---|
| Moneyline (Elo) | 1322 | 0.2218 / 0.2096 | 0.636 / 0.607 | 0.79 | 988 | −6.4% (at close) | n/a | LOSES_TO_CLOSE |
| Spread (Elo) | 1181 | 0.2677 / 0.2500 | 0.732 / 0.693 | −0.19 | 861 | −6.3% (−110 assumed) | +0.006 | LOSES_TO_CLOSE |
| Total (V2) | 1182 | 0.2734 / 0.2500 | 0.745 / 0.693 | −0.27 | 868 | −4.3% (−110 assumed) | +0.001 | LOSES_TO_CLOSE |

Negative calibration slopes on spread/total mean the model's lean vs the close line has no (slightly inverse) predictive value. Archive lacks spread/total prices and ML opens; see caveats in `results.json`.

Rerun: `python backtests/nba/2026-10-24/backtest_nba.py --source <nba_archive_10Y.json>`
