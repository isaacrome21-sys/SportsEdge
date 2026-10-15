# Pre-registration: NBA game-market walk-forward on 2025-26 (fresh out-of-sample season)

Committed before any 2025-26 data was fetched or scored. **Governance flag:** this is a new pre-registration path and needs ChatGPT freeze-inventory registration. Research only. Lines are NAIVE stand-ins; market baseline MISSING; rest_adj = 0.

## Why this is fresh
The model (`asof_team_ratings` V1 + `quarter_joint_sim` V1) and the harness were built and examined on 2024-25 only. 2025-26 has never been loaded by this lane.

## Frozen, no changes
- Code is exactly as on this branch at the prereg commit: `scripts/run_nba_asof_harness.py`, `asof_harness.py`, `asof_team_ratings.py`, `quarter_joint_sim.py`. There is no tuning, no parameter change and no carry-over of 2024-25 fits.
- The walk-forward starts cold, as in 2024-25. Each season is self-contained: per slate, it fits only on 2025-26 games that started before that day's first tip, and teams need ≥ 10 prior games.

## Data
- Free ESPN `scoreboard` + `summary` for completed regular-season games (season type 2) from 2025-10-21 through 2026-04-12, using the same fields as 2024-25.
- Cached outside the repo (`/workspace/nba_cache_q_2025_26`).
- The same fetch script is used, with only the date range and cache directory changed.

## Metrics and decision (fixed)
- **Markets:** MONEYLINE, SPREAD and TOTAL (naive proxy lines), plus the H1 and Q1 total stand-ins as reported by the harness.
- **PASS_RESEARCH** iff model Brier < naive Brier **and** model log-loss < naive log-loss for MONEYLINE, SPREAD **and** TOTAL. H1/Q1 are reported, not gating. Otherwise FAIL.
- The result is reported in full, regardless of outcome.
