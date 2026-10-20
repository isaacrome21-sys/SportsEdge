# NBA fresh harness run (2026-10-19)

Replaces the unverifiable Oct 11 CONDITIONAL_PASS (n=1,306 counted overlapping walk-forward windows; at most 190 distinct games existed).

- Inputs: 43 scoreboard caches at `../nba_oct11_harness/cache/` (ref 6edee1b0), all 43 sha256 match `MANIFEST.sha256`.
- 310 completed games parsed; 186 scored, each exactly once, by a model fit only on games that tipped off >= 1 day earlier, once >= 120 training games existed.
- Candidate: `fit_verified_games` + `price_game_markets` home ML probability. Baseline: training home-win rate.
- Brier 0.23374 vs 0.24826; delta -0.01452; 95% CI game-clustered [-0.0266, -0.0021], date-clustered [-0.0258, -0.0026] (seed 20261017, 2000 resamples).
- Margin MAE 11.8, total MAE 14.0.
- **Market leg: MISSING.** No captured DK prices for these games, so this beats a naive base rate only. Status: market never measured. No PLAY.

Re-run: `python3 fresh_run.py <repo_root> <cache_dir_of_decoded_json> <out_dir>`. Rows: `per_game_rows.csv` (sha256 in summary.json).