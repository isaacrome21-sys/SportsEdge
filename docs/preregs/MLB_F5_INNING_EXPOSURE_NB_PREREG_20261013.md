# MLB F5 inning-exposure negative-binomial distribution — pre-registration (2026-10-13)

Status: PRE-REGISTERED, NOT EVALUATED. Research only. No activation, no pricing,
no promotion, no staking. `config/deployments.json` F5_* `eligible=false` is not
changed by this document or by any result it produces.

## 0. Holdout hygiene
- #2156 zero-inflated F5 dispersion (2024 fit / 2025 holdout) FAILED. 2024 and 2025
  (and the 2025 holdout of MLB_F5_NRFI_TIGHTENING_PREREG) are BURNED as evaluation
  windows for any F5/first-inning claim. They may be used only as training history.
- No parameter, form or threshold below may be tuned on 2024/2025 holdout results.
- Evaluation window: **2027 MLB regular season only**, untouched. The 2026 postseason
  is NOT used (games before this commit have already been observed).

## 1. Model (frozen)
Per team-half, F5 runs = sum over innings 1..5 of inning runs. Each inning i for
batting team T vs pitching side P:
- Exposure split: starter share s_i = P(starter still pitching at start of inning i),
  bullpen share 1 - s_i. s_i estimated from the starter's strictly-prior starts
  (last 10 starts, 370-day lookback, min 3; else league strictly-prior s_i by inning).
- Inning mean: mu_i = r_T,i * [s_i * a_S + (1 - s_i) * a_B], where r_T,i = batting
  team's strictly-prior per-inning runs for inning slot i (inning 1 separate; 2–5 pooled),
  a_S = starter runs-allowed index (strictly-prior, Gamma-shrunk to league with
  prior weight 60 batters faced), a_B = team bullpen runs-allowed index (strictly-prior,
  shrunk with prior weight 30 innings). Indices are ratios to league strictly-prior mean.
- Inning count distribution: NB2 with mean mu_i and a single league dispersion k
  fit by MLE on training innings only. Innings independent; F5 half total = convolution.
  Two halves independent; home and away convolved to a joint score grid 0..30.
- Starter identity MUST come from `mlb_pregame_starter_adapter` (verified pregame
  binding). No bound starter -> row BLOCKED, no fallback to retrospective boxscore starter.
- Probabilities are produced from the grid only; no market price enters the model.

## 2. Settlement (explicit)
- F5 ML two-way (tie = push/void): p_away' = P(A>H)/(1-P(A=H)); push mass reported.
- F5 ML three-way: P(A>H), P(A=H), P(H>A) reported separately; never collapsed.
- F5 run line / totals: integer lines carry explicit push mass; half lines none.
- Graded only on games with 5 complete innings (4.5 if home leads is NOT treated as final
  for F5; such games are excluded and counted). Suspended/shortened -> excluded and counted.

## 3. Data (frozen)
- Free MLB StatsAPI schedule+linescore+boxscore, regular season, sportId=1.
- Training: 2021–2026 regular-season games with status Final strictly before
  2026-10-13T00:00:00Z cutoff. Every feature for a target game uses only games final
  on dates strictly before the target date. No paid data, no backfill of capture.
- Raw response SHA-256 and fetch time recorded per file; no timestamp manufactured.

## 4. Baselines (frozen)
- B1 naive: league strictly-prior F5 score-state empirical distribution (Jeffreys-smoothed).
- B2 full-game scaled: strictly-prior team full-game run Poisson means scaled by
  league strictly-prior F5/full-game run ratio, independent Poisson halves.
- Market baseline: DK F5 prices only if genuinely captured pregame; otherwise reported
  MISSING (not substituted).

## 5. Metrics and decision rule (frozen)
Primary: mean log loss on (a) three-way F5 result, (b) F5 total over/under at
4.5 and 5.5, (c) home F5 team total over 2.5. Secondary: Brier, calibration slope/
intercept (10 bins), ranked probability score on total runs.
PASS_RESEARCH only if the candidate beats BOTH B1 and B2 on every primary target,
with paired bootstrap (game-level, 2000 resamples, seed 20261013) 95% CI of the
log-loss difference excluding zero. Anything else = FAIL; no re-fit on 2027.
PASS_RESEARCH grants no eligibility; promotion requires the separate market and
forward-evidence gates.

## 6. Freeze
Code implementing §1 must be committed and SHA-pinned before 2027-03-01; the
evaluation runs once, after the 2027 regular season ends.
