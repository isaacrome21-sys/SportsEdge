# SportsEdge MONEYLINE V6 Tail/Discrimination Protocol — 2026-08-13

## Status
PREDECLARED before any V6 deployment decision. This protocol does not change or
reinterpret the frozen V5 holdout result. It defines additional evidence required
for any successor moneyline model to replace the temporary production risk guard.

## Why this protocol exists
The current GAME_SCORE_V5_STATCAST 2025 moneyline acceptance test checks aggregate
calibration (`home_ml` z <= 2.5) but does not require probability-bucket calibration,
monotone discrimination, or tail-specific performance. A model can therefore be
close to the unconditional home-win rate and pass aggregate calibration while
remaining weak at separating strong favorites from true underdogs. Production also
previously accepted any positive-EV candidate with a zero raw-edge floor.

This protocol treats the heavy-underdog region as UNVALIDATED until direct evidence
supports it. It is not a claim that favorites are inherently profitable.

## Frozen development chronology
- Existing observed data through 2026-08-12 may be used for development only.
- Any candidate intended for deployment must be frozen before its forward-shadow
  evidence begins.
- Sportsbook prices may be used downstream for selection/CLV diagnostics but may
  not enter Model_P features or model fitting.
- If a historical market-price sample is used to choose thresholds, that sample
  becomes development evidence and cannot simultaneously count as final validation.

## Required model-only validation
A successor ML artifact must satisfy all of the following on a predeclared untouched
or genuinely forward sample:

1. **Aggregate calibration**
   - absolute calibration z <= 2.5.

2. **Probability-bucket calibration**
   - evaluate fixed Model_P buckets: [0,.40), [.40,.50), [.50,.60), [.60,1].
   - a bucket is scored only when n >= 100; insufficient buckets are reported,
     never silently dropped.
   - every scored bucket must have absolute calibration z <= 3.0.

3. **Monotone lift**
   - observed home-win rate must be nondecreasing across scored Model_P buckets,
     allowing a 2.0 percentage-point sampling tolerance between adjacent buckets.
   - if this fails, deployment is blocked even if aggregate calibration passes.

4. **Brier skill versus unconditional baseline**
   - compute Brier score of the candidate and the sample's predeclared/base-rate
     benchmark without refitting the candidate.
   - candidate Brier must be strictly lower than baseline Brier.
   - report Brier skill = 1 - candidate_brier / baseline_brier.
   - no positive minimum beyond >0 is invented after seeing the final sample.

5. **Log-loss skill versus unconditional baseline**
   - candidate log loss must be strictly lower than the same unconditional baseline.

6. **Discrimination**
   - report ROC AUC and probability standard deviation.
   - AUC must be > 0.50 on the validation sample.
   - no stronger AUC threshold may be added after seeing the final sample without
     starting a new predeclared protocol/sample.

## Required market-tail validation before removing the production dog guard
This section is downstream wager-selection validation and is separate from Model_P
fitting. Prices must be timestamped pregame and identity-bound.

Fixed underlying-moneyline bands:
- favorite: <= -100
- short/moderate underdog: +100 through +174
- heavy underdog: +175 and longer

For each band, report:
- number of candidates and official selections,
- average Model_P,
- average no-vig market probability when both sides are available,
- average Model_P minus no-vig market probability,
- win rate,
- Brier/log loss,
- closing-line probability delta when a legitimate close is available,
- realized ROI as descriptive evidence only.

Heavy-underdog side betting remains blocked unless the frozen/forward sample contains
at least 100 heavy-underdog candidate observations and demonstrates all of:
- positive mean closing-line probability delta,
- nonnegative Brier skill versus the no-vig market probability baseline,
- no tail calibration bucket with absolute z > 3.0.

These are promotion requirements, not thresholds to tune against the same sample.

## Production safety overlay while V6 evidence is pending
GAME_RISK_GUARD_V1_20260813 remains downstream of Model_P:
- global game-market raw-edge floor: 2.5pp;
- underlying ML +175 or longer: no official ML/RL side exposure;
- +100 through +174: at least 5.0pp edge and 10% EV;
- dog Model_P/market disagreement above 7.5pp is unvalidated and passes;
- dog Kelly guidance capped at 1.5%;
- at most one ML/RL side exposure per game.

The overlay cannot promote a candidate that failed the base Truth Gate. It may only
turn an otherwise-official candidate into PASS or reduce stake guidance.

## Supersession rule
The temporary guard may be loosened only by a new commit that cites the exact
validation artifact/sample, candidate SHA-256, source cutoff, and results satisfying
this protocol. A losing streak or winning streak alone is not sufficient evidence.
