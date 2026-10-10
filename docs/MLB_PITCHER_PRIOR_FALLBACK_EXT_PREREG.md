# MLB few-starts pitcher fallback, extension to BB / H / ER — pre-registration (v1, 2026-10-10)

Tracking: #1482. Written and committed **before** any BB/H/ER result was seen. The
runner prints the SHA-256 of this file so the result comment is bound to it.

## Problem
The validated few-starts fallback (#1495, `docs/MLB_PITCHER_PRIOR_FALLBACK_PREREG.md`,
production #1500) prices only PITCHER_OUTS and PITCHER_K for starters with 1–4
prior starts. PITCHER_BB, PITCHER_HITS_ALLOWED and PITCHER_ER stay BLOCKED with
`insufficient chronological sample k<5` (live example: Hagen Smith, k=1, #1873,
where BB 0.5 / H 1.5 / ER 0.5 / H+W+ER 2.5 were all BLOCKED).

## Candidate (frozen, no tuning)
Exactly the production fallback, applied to three more stats:
own k prior starts (weight 1 each) + `m = 4` pseudo-starts from the `league_short`
pool of season Y-1, effective n = k + 4, production Jeffreys posterior (alpha 0.5)
on half-integer lines. Pool and m are the #1495 selection, **not re-selected**.
There is no grid and no tuning step in this protocol.

`league_short` (as in #1495): starts in season Y-1 made when that pitcher had <5
prior starts in his production window (seasons Y-2..Y-1, strictly earlier dates).

## Data
MLB StatsAPI pitching game logs (`gameType=R`), seasons 2022–2025, every pitcher
with `gamesStarted > 0`, same fetch as #1495. Per start: `baseOnBalls`, `hits`,
`earnedRuns` (plus outs/K, unchanged).

## Units
Every regular-season start in season Y where the pitcher had k ∈ {1,2,3,4} prior
starts in the production window. k = 0 is reported for information only.
- **Decision season: 2025** (pool from 2024).
- **Consistency season: 2024** (pool from 2023). 2024 was used in #1495 to select
  pool/m, but only on outs/K; BB/H/ER were never looked at.

## Metrics
- Primary: RPS = sum of Brier scores over half-integer lines t + 0.5:
  BB t = 0..9, H t = 0..14, ER t = 0..11 (values above the top line are clipped).
- Comparator: own-only (k own starts, Jeffreys, n = k) — the price production would
  emit if the k<5 block were simply removed.
- Secondary: binary log loss and 10-bin ECE at typical lines
  BB {0.5, 1.5, 2.5}; H {2.5, 3.5, 4.5, 5.5}; ER {0.5, 1.5, 2.5}.
- Reference ECE: own-only last-10 Jeffreys on 2025 k ≥ 5 starts.

## Ship rule (evaluated independently per market; all must hold for that market)
1. 2025: mean RPS(fallback) − RPS(own-only) has a 95% pitcher-clustered bootstrap
   CI (2000 reps, seed 20261010) entirely below 0.
2. 2025: fallback typical-line ECE ≤ max(0.03, reference ECE + 0.01).
3. 2024: the point estimate of RPS(fallback) − RPS(own-only) is < 0 (sign
   consistency on the untouched-for-these-stats season).

A market that passes may only replace BLOCKED for k = 1..4 on half lines; k = 0,
integer lines, PITCHER_HITS_WALKS_ER and EITHER_PITCHER markets stay BLOCKED.
Rows stay LEAN max; nothing is promoted. A market that fails stays BLOCKED, and the
failure is reported as a failure — no re-run with a different pool or m.

## Production wiring (only for markets that ship)
A separate PR re-emits the frozen 2025 `league_short` pool with BB/H/ER counts,
lets `pitcher_joint_engine` accept those markets on the fallback path, and adds a
test that engine prices equal this research code to 1e-12. Until then nothing in
production changes.

## How it runs
Open an `[MLB LINES]` issue whose fenced body is `RESEARCH pitcher_prior_fallback_ext`.
The intake runs `scripts/research_mlb_pitcher_prior_fallback_ext.py` in Actions
and posts the report on that issue. No lines are read and no card is produced.
