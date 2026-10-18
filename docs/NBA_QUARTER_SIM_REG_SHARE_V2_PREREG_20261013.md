# Pre-registration: NBA quarter sim V2 regulation-share fix (fit 2024-25, holdout 2025-26)

This doc was committed **before** V2 code was written and before any V2 number was computed.

**Governance flag:** this is a new pre-registration path, so it needs ChatGPT freeze-inventory registration. It is research only. Lines are naive stand-ins, the market baseline is MISSING, and rest_adj = 0.

## Disclosure
- Both season caches (`/workspace/nba_cache_q`, 2024-25; `/workspace/nba_cache_q_2025_26`, 2025-26) were already fetched.
- V1 results on both seasons are already known: see `NBA_QUARTER_SIM_2025_26_OOS_RESULT_20261013.md`.
- 2025-26 per-quarter, regulation and OT statistics have **not** been examined beyond those V1 Brier and log-loss figures.

## Problem (from code reading, not data)
In V1, `simulate` scales the full-game rating mean by a pooled `reg_share` (regulation points / final points), and then adds simulated OT on top. The expected simulated final therefore equals `mean*reg_share + E[sim OT points]`.

That is not the rating mean, because:
- the sim's own tie and OT rate differs from the pooled historical rate;
- the pooled share applies the same OT deduction regardless of matchup closeness.

V1 also recalibrates every quarter parameter cold, in-season, from the first ~30 games.

## V2 (fixed rules, no free parameters fit on 2025-26)
1. **Calibration constants are frozen from 2024-25.** `calibrate()` runs once on **all** 2024-25 quarter games. That fixes shares, resid_sd, rho, ot_mean and ot_sd, and they are never updated during 2025-26.
2. **Regulation mean is moment-matched.** For each game, the regulation means start at `(home_mean, away_mean) * reg_share`.
   - Simulate once, then shift both regulation means by the same additive `d = (home_mean + away_mean - E_sim[final total]) / 2`.
   - Re-simulate with the same seed. That makes exactly one correction step, fixed.
   - The margin is preserved because the shift is equal on both sides.
3. Everything else is unchanged: the as-of team ratings (walk-forward on 2025-26 only, as in V1), n_paths = 3000, the same seeds, min_team_games = 10, and the same naive train-mean lines from 2025-26 games before each slate.

## Comparison (holdout 2025-26 only)
- Arms: **V1** (current harness, unchanged) vs **V2**, on identical games and lines.
- Markets, all over-probabilities read from the sim paths against naive train-mean stand-in lines: **full-game TOTAL**, **H1 total**, **Q1 total**.
- Diagnostics are reported and are not gating:
  - mean (sim expected total − actual total);
  - sim OT rate vs actual OT rate;
  - ML Brier from the sim.

## Decision (fixed)
- **PASS_RESEARCH** iff V2 Brier < V1 Brier **and** V2 log-loss < V1 log-loss on **at least two of three** markets (TOTAL, H1, Q1), and V2 is worse than V1 by no more than 0.002 Brier on any of the three.
- Otherwise the result is **FAIL**, and V1 stays.
- The result is reported in full regardless of outcome. A PASS changes nothing beyond research: there is no promotion, and the market baseline stays MISSING.
