# SportsEdge MLB V5 Moneyline favorite/underdog calibration predeclaration

Committed before running the new favorite-vs-underdog diagnostic requested on 2026-08-13.

This protocol does **not** change Model_P, refit the deployed V5 GAME artifact, loosen any validation threshold, or force favorite selections. Its purpose is to decide whether the observed underdog-heavy card is consistent with calibrated probabilities plus payout arithmetic or reflects a localized calibration defect.

## 1. Frozen classification

A MONEYLINE candidate is classified from the contemporaneous pregame sportsbook price used only for evaluation/wagering, never as a Model_P feature:

- FAVORITE: American odds < -100
- PICKEM: -100 or +100; report separately, do not use to pass either favorite or dog gate
- UNDERDOG: American odds > +100

Underdog price bands are frozen as:

- DOG_100_124: +101 through +124
- DOG_125_149: +125 through +149
- DOG_150_174: +150 through +174
- DOG_175_PLUS: +175 and longer

Model-probability buckets are frozen as [0.20,0.30), [0.30,0.40), [0.40,0.50), [0.50,0.60), [0.60,0.70), [0.70,0.80), with out-of-range tails reported separately. Only buckets with n >= 100 may independently qualify/fail a calibration-bucket gate; smaller buckets are reported but are not used to declare the region validated.

## 2. Evidence identity and chronology

The diagnostic may use only rows whose Model_P, sportsbook quote timestamp, game identity and model/artifact identity were frozen before first pitch. Outcome attachment must occur later and may not mutate the prediction/decision record.

One team/game MONEYLINE prediction counts once. Repeated scheduled snapshots may not inflate n. If multiple valid snapshots exist for the same team/game, use the latest complete valid snapshot strictly before first pitch.

Cancelled/postponed games are excluded. Suspended/resumed games require an explicit chronology-safe rule and otherwise fail closed.

Historical diagnostic results may identify a defect but may **not by themselves loosen** the interim underdog concentration guard. Relaxing the guard requires genuinely forward evidence collected after this protocol commit.

## 3. Predeclared diagnostic metrics

For FAVORITE and UNDERDOG groups separately, and for each qualifying dog price band/model-P bucket, compute:

1. n
2. mean Model_P
3. realized win rate
4. calibration bias = mean Model_P - realized win rate
5. calibration z = abs(mean Model_P - realized win rate) / sqrt(mean(p*(1-p))/n)
6. Brier score
7. log loss
8. Brier skill versus a constant within-group base-rate predictor
9. monotonicity of realized win rate across ordered Model_P buckets

If a valid no-vig contemporaneous market probability is present in the frozen ledger, also report market Brier/log loss as a comparator. Market probability is evaluation-only and remains prohibited from Model_P.

## 4. Frozen pass/fail bar for underdog calibration

The general underdog region may be called CALIBRATION_VALIDATED only if all of the following hold on the required forward sample:

- at least 200 unique UNDERDOG MONEYLINE observations with outcomes;
- overall underdog absolute calibration bias <= 0.020;
- overall underdog calibration z <= 2.50;
- every qualifying Model_P bucket with n >= 100 has absolute calibration bias <= 0.030 and calibration z <= 2.50;
- every qualifying dog price band with n >= 100 has absolute calibration bias <= 0.030 and calibration z <= 2.50;
- underdog Brier score is no worse than the constant underdog base-rate Brier score;
- underdog log loss is no worse than the constant underdog base-rate log loss;
- realized win rate is nondecreasing across qualifying Model_P buckets, allowing at most one adjacent inversion whose magnitude is <= 0.020;
- no chronology, identity, artifact-version, quote-timestamp or sportsbook-to-Model_P contamination violation occurs.

The +175-and-longer region remains separately unvalidated unless DOG_175_PLUS itself has at least 150 unique forward observations and independently satisfies bias <= 0.030 and z <= 2.50. Passing the general dog gate does not automatically validate this tail.

## 5. Frozen favorite comparison bar

The same overall bias/z/Brier/log-loss metrics are reported for FAVORITE rows. A favorite calibration failure does not make dogs valid and a dog failure does not make favorites valid. SportsEdge must not manufacture favorite bets to balance the card.

## 6. Interim wager policy before the forward dog gate passes

Until Section 4 passes:

- maximum one OFFICIAL underdog MONEYLINE per MLB slate;
- maximum two OFFICIAL underdog side positions total across MONEYLINE and RUN_LINE per slate;
- total Kelly guidance across all underdog side positions is capped at 0.020 of bankroll per slate;
- existing +100 to +174 dog minimum edge/EV/disagreement gates remain in force;
- +175-and-longer side exposure remains blocked;
- favorite bets still require the normal edge/EV gates; none are forced for cosmetic balance.

These are downstream portfolio controls only and do not alter Model_P.

## 7. Generic minimum-edge contract

Before HITS, TOTAL_BASES, PITCHER_BB, NRFI or YRFI can produce a newly official wager through the generic automated runner, its default minimum edge must be nonzero and at least 0.025 unless a market-specific predeclared threshold is stricter. A caller may not silently obtain a zero-edge official-bet policy by omitting a CLI argument.

This rule must be covered by regression tests before newly eligible prop markets are allowed to depend on the generic runner.

## 8. Full Model presentation contract

Presentation must not change wager verdicts. Every Full Model run should expose four sections:

1. OFFICIAL BETS — only deployment-eligible candidates that pass pricing, edge and portfolio gates.
2. PROP SHADOW BOARD — priced/model-scored prop candidates that are not deployment eligible, clearly marked non-official.
3. REJECTED CANDIDATES — otherwise interesting candidates with the exact fail-closed reason (dog concentration, calibration region, stale price, insufficient edge, etc.).
4. NO-EDGE / EVALUATED — evaluated favorites and other markets that simply did not clear a wager threshold.

A sparse official card must never make evaluated markets silently disappear.

## 9. Change control

The thresholds above are frozen before examining the requested favorite-vs-underdog calibration diagnostic. If the diagnostic fails, the response is a new predeclared model/calibration research lane; the pass bar may not be changed after seeing the result.
