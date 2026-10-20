# NBA game-market harness validation (ML leg)

## Verdict: CONDITIONAL_PASS

Reasons:
- MARKET_BASELINE_MISSING: no archived market prices; the market-baseline leg of Isaac's bar could not be checked. Do not promote on this verdict alone.

| model | n | Brier | log loss | mean p | base rate |
|---|---:|---:|---:|---:|---:|
| candidate | 1306 | 0.2364 | 0.6652 | 0.500 | 0.500 |
| existing | 1306 | 0.2473 | 0.6877 | 0.500 | 0.500 |
| market baseline | MISSING — no archived prices; leg not checked |

Brier delta (candidate - existing): -0.0108
Log-loss delta (candidate - existing): -0.0225

## Candidate calibration (out-of-sample)

| prob bin | n | mean p | hit rate |
|---|---:|---:|---:|
| 0.0-0.1 | 0 | — | — |
| 0.1-0.2 | 0 | — | — |
| 0.2-0.3 | 35 | 0.273 | 0.314 |
| 0.3-0.4 | 227 | 0.357 | 0.339 |
| 0.4-0.5 | 391 | 0.453 | 0.481 |
| 0.5-0.6 | 391 | 0.547 | 0.519 |
| 0.6-0.7 | 227 | 0.643 | 0.661 |
| 0.7-0.8 | 35 | 0.727 | 0.686 |
| 0.8-0.9 | 0 | — | — |
| 0.9-1.0 | 0 | — | — |

_research_only: no betting authority. min_n=30._
## Spread/total point-forecast diagnostics (not part of the verdict)

No market lines exist to settle spread/total as binary outcomes (no Odds API by Isaac's choice), so these are MAE diagnostics only.

- n test games: 653
- margin MAE: candidate 11.83 vs naive 12.37
- total MAE: candidate 14.36 vs naive 15.08

## Provenance

- 310 real 2024-25 NBA games from the free ESPN scoreboard API (2024-10-23 to 2025-04-10, every 4th day), cached at `data/backtest_nba_cache/`
- candidate: sportsedge.sports.nba.nba_game_market_pricing (ratings replay on train only, residual sigmas from train)
- existing: naive train home-win-rate (ML) / train league averages (margin/total diagnostics)
- market baseline: MISSING (no Odds API)
- research only; no betting authority.
