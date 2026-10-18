# NBA as-of ratings harness — 2024-25 regular season (research only)

Module: `sportsedge/sports/nba/asof_team_ratings.py` (VERSION NBA_ASOF_TEAM_RATINGS_V1_20261013), harness `sportsedge/sports/nba/asof_harness.py`, runner `scripts/run_nba_asof_harness.py`.

- Data: 1,234 completed regular-season games from the free ESPN public scoreboard + summary endpoints (team box: FGA, FTA, ORB, turnovers), fetched 2026-10-13; 1,231 loaded, 3 skipped as invalid. Cache **not committed**. No odds, no paid calls.
- Walk-forward: per slate date, fit on games strictly before that day's first tip; teams need >=10 prior games. Margin/total SD from earlier out-of-sample residuals only.
- Spread/total events use **NAIVE_PROXY lines** (train mean margin / mean total), not market lines.
- **Market baseline: MISSING** (no paired, timestamped odds in repo). Beating naive is not a promotion criterion. rest_adj = 0.

```json
{
  "MONEYLINE": {
    "n": 1076,
    "model_brier": 0.2114,
    "model_logloss": 0.60989,
    "naive_brier": 0.24879,
    "naive_logloss": 0.69075
  },
  "SPREAD_NAIVE_PROXY_LINE": {
    "n": 1076,
    "model_brier": 0.21332,
    "model_logloss": 0.61416,
    "naive_brier": 0.25023,
    "naive_logloss": 0.69362
  },
  "TOTAL_NAIVE_PROXY_LINE": {
    "n": 1076,
    "model_brier": 0.22732,
    "model_logloss": 0.64589,
    "naive_brier": 0.24964,
    "naive_logloss": 0.69242
  },
  "market_baseline": "MISSING_NO_PAIRED_TIMESTAMPED_ODDS",
  "rest_adj": 0.0,
  "research_only": true,
  "games_loaded": 1231,
  "games_skipped_invalid": 3
}
```

## Quarter joint simulation (V1) — 1H / Q1 totals
`sportsedge/sports/nba/quarter_joint_sim.py`: one path set per game (Q1–Q4 bivariate-normal team points with home/away correlation, integer, OT periods until untied); quarter shares, per-quarter SD, correlation, regulation share and OT scoring calibrated only on games before the slate. Full game, team totals, 1H, Q1 and ML all read from the same paths (ML vs margin inconsistency = 0.0). Pushes settled explicitly for whole-number lines.
Lines below are **NAIVE STAND-INS (train mean), not market lines**; market baseline MISSING. Data: same free ESPN summaries with quarter linescores (1,231 games; cache not committed).

```json
{
  "H1_TOTAL_NAIVE_STANDIN_LINE": {
    "n": 1076,
    "model_brier": 0.23527,
    "model_logloss": 0.66307,
    "naive_brier": 0.24951,
    "naive_logloss": 0.69217
  },
  "Q1_TOTAL_NAIVE_STANDIN_LINE": {
    "n": 1076,
    "model_brier": 0.24098,
    "model_logloss": 0.67482,
    "naive_brier": 0.25003,
    "naive_logloss": 0.69321
  },
  "lines": "NAIVE_STANDIN_TRAIN_MEAN_NOT_MARKET",
  "max_ml_vs_margin_inconsistency": 0.0,
  "market_baseline": "MISSING_NO_PAIRED_TIMESTAMPED_ODDS",
  "rest_adj": 0.0,
  "research_only": true
}
```
