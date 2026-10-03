# MLB few-starts pitcher fallback — pre-registration (v1, 2026-10-03)

Tracking: #1482 (backlog item B). Written and committed **before** any result was
seen. The research runner prints the SHA-256 of this file so the result comment is
bound to this exact protocol.

## Problem
`pitcher_joint_history` raises `insufficient chronological sample k<5` when a
starter has fewer than 5 regular-season starts in the production window (prior
season + current season, strictly before the game date). The market is then
BLOCKED (e.g. Hagen Smith, 1 start, CWS@CLE on #1457).

## Candidate fallback
Pool the pitcher's own k prior starts (weight 1 each) with a prior pool whose
total weight is `m` pseudo-starts. Posterior settlement mass uses the production
Jeffreys rule (`alpha = 0.5`) with **effective n = k + m** (not Kish ESS of the
raw rows, which would overstate certainty when a large prior pool is split into
many tiny weights). `m = inf` means prior-only (effective n = m_cap = 32).

Prior pools (all built only from the season **before** the evaluated season, so no
same-season leakage):
- `league_all`: every regular-season start in season Y-1.
- `league_short`: starts in Y-1 made when that pitcher had <5 prior starts in his
  own production window (rookie/spot-starter pool).
- `team_all`: starts in Y-1 by the pitcher's current team (team of the evaluated
  start, which is known pregame).

Grid: pool in {league_all, league_short, team_all} x m in {1, 2, 4, 8, 16, 32, inf}.

## Data
MLB StatsAPI pitching game logs (`gameType=R`), seasons 2022-2025, for every
pitcher with `gamesStarted > 0` in that season. Rows with `gamesStarted >= 1` are
starts, exactly as production. Outs from `inningsPitched` with baseball notation.

## Evaluation units
Every regular-season start in season Y where the pitcher had k in {1,2,3,4} prior
starts in the production window. k = 0 is reported separately (no own data).
- Tuning season: **2024** (pools from 2023). Select one (pool, m) minimizing the
  mean of RPS(outs)/RPS_own(outs) and RPS(K)/RPS_own(K). One setting, because the
  production pitcher pool is shared across all pitcher markets.
- Held-out season: **2025** (pools from 2024). Evaluated once with the frozen
  selection.

## Metrics
- Primary: ranked probability score (sum of Brier scores over half-integer lines
  t+0.5; outs t = 0..26, K t = 0..19) of the **engine-style posterior** P(over).
- Secondary: binary log loss and 10-bin ECE at typical lines
  (outs 14.5/15.5/16.5/17.5; K 3.5/4.5/5.5/6.5).
- Reference: production own-only (last 10 starts, k >= 5) on 2025 k >= 5 starts.

## Ship rule (all must hold on 2025)
1. Selected fallback RPS < own-only RPS for **both** outs and K, with the 95%
   pitcher-clustered bootstrap CI of the difference (2000 reps, seed 20261003)
   entirely below 0.
2. Fallback ECE at typical lines <= max(0.03, reference ECE + 0.01) for both outs
   and K.
3. If it ships, it only removes the BLOCKED state for k in 1..4. k = 0 stays
   BLOCKED (its numbers are reported for information only). Pitcher props stay
   lean-tier; this does not promote any market.

If any rule fails, the fallback does not ship and the market stays BLOCKED.

## Production wiring (only if it ships)
A separate PR passes the selected prior as weighted pool rows plus an explicit
effective n (= k + m) to `pitcher_joint_engine`, with a test proving its prices
equal this research code's predictions. Until then nothing in production changes.

## How it runs
Open an `[MLB LINES]` issue whose fenced body is `RESEARCH pitcher_prior_fallback`.
The intake script runs `scripts/research_mlb_pitcher_prior_fallback.py` in Actions
and posts the report on that issue. No lines are read and no card is produced.
