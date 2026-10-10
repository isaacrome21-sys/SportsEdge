# MLB postseason pitcher K / outs bias check — pre-registration (v1, 2026-10-10)

Tracking: #1482. Written and committed **before** the production prices below were
scored on any postseason start. The runner prints the SHA-256 of this file so the
result comment is bound to it.

## Problem
The phone card prices postseason PITCHER_K and PITCHER_OUTS with the regular-season
engine: last 10 regular-season starts (`gameType=R`, seasons Y-1..Y), Jeffreys
posterior, plus the validated opponent lanes (OPP-K beta 1, #1509; OPP-OUTS obidx
beta -0.25, #1523). That price was validated on regular-season starts only.

Postseason managers pull starters earlier, and opponents are better than average.
A context-blind check in #1852 / #1855 (2023–2025 postseason, own-history marginals
without the opponent lanes) fitted logit offsets of about -1.06 for outs and -0.79
for K, i.e. the regular-season price was too high on overs. That check did not use
the production prices, so it cannot by itself justify changing the card. Disclosure:
2023–2025 postseason outcomes have therefore been looked at (with a different model);
**2022 has not**, and gets its own sign rule below.

## Prices tested (frozen, no tuning)
Exactly the production model_p, reproduced with the research functions that are
parity-tested against the engine to 1e-12:
- PITCHER_K: `mlb_opp_k_context_research.predict_k(own, target, index, beta=1.0)`.
- PITCHER_OUTS: `mlb_opp_outs_context_research.predict_outs(own, target, indices, ("obidx", -0.25))`.
- `own` = the pitcher's last 10 regular-season starts in seasons Y-1..Y dated before
  the postseason game; units need ≥ 5 such starts (the production k ≥ 5 path).
- The opponent index is the production construction (team hitting game logs for
  seasons Y-2..Y only, strictly prior, W = 1000 PA shrinkage to Y-1), evaluated at
  the postseason date. Production refuses the lanes when any Y-2 / Y-1 team log has
  < 100 games and then prices unadjusted; the runner mirrors that. For Y = 2022 this
  happens (2020 had 60 games), so 2022 is scored at the unadjusted own-history price,
  which is what production would have emitted. The report states the lane state per
  season.
- Not reproduced: the LINEUP-K lane (#1540; needs the posted lineup, its factor on
  the live board was 1.00) and the presentation guards. Few-starts fallback rows
  (k = 1..4) are out of scope.

No parameter is fitted here. Nothing is selected. This is a calibration check of an
existing price on a population it was never validated on.

## Data and units
- Postseason games: StatsAPI schedule, `gameTypes=F,D,L,W`, seasons **2022–2025**,
  status Final. (2021 and earlier are excluded: the 60-game 2020 season would be the
  whole Y-1 window.)
- Starter of each side = first pitcher listed in the boxscore for that team; outs
  from `inningsPitched`, K from `strikeOuts`.
- Regular-season pitching game logs (`gameType=R`) for each starter, seasons Y-1, Y;
  team hitting game logs for all 30 teams, seasons 2020–2025.
- One unit = one starter-start. Scoring lines:
  K {3.5, 4.5, 5.5, 6.5}; outs {14.5, 15.5, 16.5, 17.5} (the production typical lines
  from #1509 / #1523).

## Metric
Over-bias of market M = mean over (unit, typical line) of `p_over − 1[y > line]`.
Positive means the card's over probability is too high. CI: 95% percentile bootstrap,
resampling postseason games (both starters of a game together), 2000 reps,
seed 20261010. Reported for information: per-season bias, typical-line Brier, log
loss, 10-bin ECE, mean of the own last-10 regular-season values vs the realised
postseason value, and the share of typical-line prices with p_over ≥ 0.5.

## Decision rule (per market, all must hold)
1. Pooled 2022–2025: the 95% CI of the bias excludes 0.
2. Pooled 2022–2025: |bias| ≥ 0.03 (3 percentage points, larger than the 2% EV floor).
3. 2022 alone (not looked at by #1852): the bias point estimate has the same sign.

If all hold, market M is **GUARDED**: a separate PR makes the phone card block M
(both sides) for postseason games (`game_type` F/D/L/W/P) with the reason
`MLB_POSTSEASON_PITCHER_<M>_BIASED (#<result issue>)`. model_p and regular-season
pricing do not change. No recalibrated price is shipped from this check; a corrected
postseason price would need its own pre-registration and held-out test (2027 work).
The guard is removed only by a later pre-registered check that passes.

If any rule fails, M stays as it is (LEAN max) and the failure is reported as such.
There is no re-run with other seasons, lines or windows.

## How it runs
Open an `[MLB LINES]` issue whose fenced body is `RESEARCH postseason_prop_bias`.
The intake runs `scripts/research_mlb_postseason_prop_bias.py` in Actions and posts
the report on that issue. No lines are read and no card is produced.
