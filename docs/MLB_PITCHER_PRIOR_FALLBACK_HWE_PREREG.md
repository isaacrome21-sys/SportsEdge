# MLB few-starts pitcher fallback, extension to Hits + Walks + ER — pre-registration (v1, 2026-10-10)

Tracking: #1482. Written and committed **before** any H+W+ER fallback result was seen.
The runner prints the SHA-256 of this file so the result comment is bound to it.

## Problem
The validated few-starts fallback now prices PITCHER_OUTS / PITCHER_K (#1495, #1500)
and PITCHER_BB / PITCHER_HITS_ALLOWED / PITCHER_ER (#1943, #1944, #1948) for starters
with 1–4 prior starts. PITCHER_HITS_WALKS_ER (H+W+ER) is still BLOCKED with
`insufficient chronological sample k<5` (live example: Hagen Smith, k=1, #1873,
H+W+ER 2.5). H+W+ER is a per-start sum of three correlated counts, so the
marginal BB/H/ER results do not carry over; it needs its own test.

## Candidate (frozen, no tuning)
Exactly the production fallback, applied to the per-start sum `hits + baseOnBalls +
earnedRuns`: own k prior starts (weight 1 each) + `m = 4` pseudo-starts from the
`league_short` pool of season Y-1, effective n = k + 4, production Jeffreys
posterior (alpha 0.5) on half-integer lines. Pool and m are the #1495 selection,
**not re-selected**. There is no grid and no tuning step.

`league_short` (as in #1495 / #1943): starts in season Y-1 made when that pitcher
had <5 prior starts in his production window (seasons Y-2..Y-1, strictly earlier
dates). The pool's H+W+ER values are the per-start sums (joint, not a convolution
of marginals).

## Data
MLB StatsAPI pitching game logs (`gameType=R`), seasons 2022–2025, every pitcher
with `gamesStarted > 0`; same fetch and start filter as #1943.

## Units
Every regular-season start in season Y where the pitcher had k ∈ {1,2,3,4} prior
starts in the production window. k = 0 is reported for information only.
- **Decision season: 2025** (pool from 2024).
- **Consistency season: 2024** (pool from 2023). 2024 was used in #1495 to select
  pool/m on outs/K only; H+W+ER was never looked at in any season.

## Metrics
- Primary: RPS = sum of Brier scores over half-integer lines t + 0.5, t = 0..24
  (values ≥ 25 are clipped into the top bin).
- Comparator: own-only (k own starts, Jeffreys, n = k) — the price production would
  emit if the k<5 block were simply removed.
- Secondary: binary log loss and 10-bin ECE at typical lines {2.5, 4.5, 6.5, 8.5, 10.5}
  (fixed now; the DK pitcher-prop archive has no H+W+ER quotes to derive them from).
- Reference ECE: own-only last-10 Jeffreys on 2025 k ≥ 5 starts.

## Ship rule (all must hold)
1. 2025: mean RPS(fallback) − RPS(own-only) has a 95% pitcher-clustered bootstrap
   CI (2000 reps, seed 20261010) entirely below 0.
2. 2025: fallback typical-line ECE ≤ max(0.03, reference ECE + 0.01).
3. 2024: the point estimate of RPS(fallback) − RPS(own-only) is < 0.

If it passes, it may only replace BLOCKED for PITCHER_HITS_WALKS_ER with k = 1..4 on
half lines ≤ 24.5; k = 0, integer lines and EITHER_PITCHER markets stay BLOCKED.
Rows stay LEAN max; nothing is promoted. If it fails, H+W+ER k<5 stays BLOCKED and
the failure is reported as a failure — no re-run with a different pool, m or lines.

## Production wiring (only if it ships)
A separate PR commits the frozen 2025 `league_short` H+W+ER pool (emitted by
`RESEARCH pitcher_prior_pool_hwe`, cross-checked against the committed base pool:
same start count, identical outs/K counts), lets `pitcher_joint_engine` accept
PITCHER_HITS_WALKS_ER on the fallback path, and adds a test that engine prices equal
this research code to 1e-12. Until then nothing in production changes.

## How it runs
Open an `[MLB LINES]` issue whose fenced body is `RESEARCH pitcher_prior_fallback_hwe`.
The intake runs `scripts/research_mlb_pitcher_prior_fallback_hwe.py` in Actions and
posts the report on that issue. No lines are read and no card is produced.
