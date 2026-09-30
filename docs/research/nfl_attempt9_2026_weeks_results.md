# Attempt 9 vs 2026 weeks 1–3 — one-shot

Frozen owner. No coefficient change. Window: 2026-09-01 → 2026-09-30 exclusive.
48 regular-season finals, 0 skipped (prior-season history unlocked every team).

Source: nflverse `games.csv` pulled 2026-09-30T03:26:30Z. Closing lines are settle/reference only and were not features.

## Point forecasts (RMSE)

| | Attempt 9 | Closing line |
|---|---:|---:|
| Home margin | 13.24 | 13.13 |
| Game total | 16.03 | 14.35 |

## Half-point posted lines only

Integer 3/7 spreads were excluded (`NO_MODEL`).

| Market | n | Predicted | Observed | \|gap\| pp | Brier |
|---|---:|---:|---:|---:|---:|
| Over close total | 48 | 0.503 | 0.479 | 2.36 | 0.287 |
| Home cover close spread | 33 | 0.481 | 0.576 | 9.53 | 0.257 |

## Read

Totals are close to calibrated on this short window. Side/cover is not: the model is short about 9.5 points of home-cover rate against the posted half-point spreads. Do not treat weekend sides as sharp. Totals at `.5` are the only market this owner currently defends.

`NOT Model_P / NOT Truth Gate / NOT OFFICIAL`.
This window is now spent for the frozen owner.
