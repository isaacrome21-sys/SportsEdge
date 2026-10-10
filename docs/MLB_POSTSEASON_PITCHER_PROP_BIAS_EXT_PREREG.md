# MLB postseason pitcher BB / H / ER / H+W+ER bias check — pre-registration (v1, 2026-10-10)

Tracking: #1482. Follow-up to #1967 / #1968 (K and outs, GUARDED by #1969). Written and
committed **before** the production prices below were scored on any postseason start.
The runner prints the SHA-256 of this file so the result comment is bound to it.

## Problem
#1968 found that the regular-season production price overstates postseason overs for
PITCHER_K (+0.117) and PITCHER_OUTS (+0.208): starters go fewer batters deep in the
postseason. The other single-pitcher count markets on the phone card — PITCHER_BB,
PITCHER_HITS_ALLOWED, PITCHER_ER and PITCHER_HITS_WALKS_ER — are priced from the same
regular-season own history and are exposed to the same workload effect, partly offset
by stronger postseason lineups (more baserunners per inning). The direction and size
are not known. These four markets have not been scored on postseason outcomes before
(#1852 / #1855 and #1968 looked at K and outs only).

## Prices tested (frozen, no tuning)
Exactly the production model_p for the k ≥ 5 path, computed by calling
`pitcher_joint_engine.price_pitcher_market` (side OVER) on features built the way
`mlb_generic_features.feature_row` builds them:
- `history_pool` = the pitcher's last 10 regular-season starts (`gameType=R`,
  `gamesStarted ≥ 1`) in seasons Y-1..Y dated strictly before the postseason game,
  ordered by date; units need ≥ 5 such starts.
- PITCHER_HITS_ALLOWED, PITCHER_ER, PITCHER_HITS_WALKS_ER also get `prior_pool` =
  starts 11–30 back in the same window when there are ≥ 5 of them (production
  `pitcher_joint_prior_rows`); otherwise no prior pool, as in production.
- PITCHER_BB: own history only. **Not reproduced:** the UMP-BB lane (#1528), which
  needs the plate umpire and the umpire walk index at game time. It is a
  multiplicative rescale by the umpire's relative walk rate and is roughly
  mean-neutral across umpires, so it cannot remove a workload bias; the lane-off
  price is what is scored, and the report says so.
- Few-starts fallback rows (k = 1..4) are out of scope. Integer lines are not scored.

No parameter is fitted here. Nothing is selected. This is a calibration check of an
existing price on a population it was never validated on.

## Data and units
- Postseason games: StatsAPI schedule, `gameTypes=F,D,L,W`, seasons **2022–2025**,
  status Final — the same game set as #1968.
- Starter of each side = first pitcher listed in the boxscore for that team; BB from
  `baseOnBalls`, H from `hits`, ER from `earnedRuns`; H+W+ER is their sum.
- Regular-season pitching game logs (`gameType=R`) for each starter, seasons Y-1, Y.
- One unit = one starter-start. Scoring lines (the typical lines frozen in #1943 /
  #1956, before any postseason data):
  BB {0.5, 1.5, 2.5}; H {2.5, 3.5, 4.5, 5.5}; ER {0.5, 1.5, 2.5};
  H+W+ER {2.5, 4.5, 6.5, 8.5, 10.5}.

## Metric
Over-bias of market M = mean over (unit, typical line) of `p_over − 1[y > line]`.
Positive means the card's over probability is too high. CI: 95% percentile bootstrap,
resampling postseason games (both starters of a game together), 2000 reps,
seed 20261010 — the #1968 code path. Reported for information: per-season bias,
typical-line Brier, log loss, 10-bin ECE, mean of the own last-10 regular-season values
vs the realised postseason value, and the share of typical-line prices with p_over ≥ 0.5.

## Decision rule (per market, all must hold — same rules as #1967)
1. Pooled 2022–2025: the 95% CI of the bias excludes 0.
2. Pooled 2022–2025: |bias| ≥ 0.03 (3 percentage points, larger than the 2% EV floor).
3. 2022 alone: the bias point estimate has the same sign (replication check).

If all hold, market M is **GUARDED**: a separate PR adds M to the phone card's
postseason block list (both sides, `game_type` F/D/L/W/P) with the reason
`MLB_POSTSEASON_<M>_BIASED (#<result issue>)`, next to the #1969 entries. model_p and
regular-season pricing do not change. No recalibrated price is shipped from this
check; a corrected postseason price would need its own pre-registration and held-out
test (2027 work). The guard is removed only by a later pre-registered check that passes.

If any rule fails, M stays as it is (LEAN max) and the failure is reported as such.
Four markets are tested at once without a multiplicity correction; the action on a
pass is only to block rows (no new bets), so a false pass costs LEAN rows, not money.
There is no re-run with other seasons, lines or windows.

## How it runs
Open an `[MLB LINES]` issue whose fenced body is `RESEARCH postseason_prop_bias_ext`.
The intake runs `scripts/research_mlb_postseason_prop_bias_ext.py` in Actions and posts
the report on that issue. No lines are read and no card is produced.
