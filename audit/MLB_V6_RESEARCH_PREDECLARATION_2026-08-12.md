# SportsEdge MLB V6 research predeclaration — 2026-08-12

Status: RESEARCH ONLY. V5 remains frozen and operational while V6 earns independent evidence.

## Objective
Test whether adding full-lineup, bullpen, platoon/arsenal, park/weather/umpire/catcher and market-specialized ensemble features improves out-of-sample calibration and betting utility without sportsbook contamination or temporal leakage.

## Candidate feature families fixed before V6 evaluation

1. Full batting order slots 1-9: prior-only expected-contact score, xBA-style contact probability, barrel rate, hard-hit rate, average exit velocity, handedness and expected PA share.
2. Starting pitcher: prior-only contact suppression, pitch mix, velocity, movement/location summaries, handedness, days rest, recent workload and times-through-order exposure proxy.
3. Bullpen: reliever aggregate prior-only quality plus prior 1/2/3-day workload and high-leverage availability proxy.
4. Platoon/arsenal: handedness interactions and hitter contact/outcome quality against pitcher pitch-family distribution.
5. Environment: park factor, temperature, wind direction/speed, roof state and umpire run environment, each with source/freshness requirements.
6. Catcher: exact starting-catcher MLBAM identity plus prior-only receiving/framing run-value residual derived from taken Statcast pitches. Catcher identity is sourced from official lineup/boxscore state and/or Statcast `fielder_2`; it is never guessed from roster membership.
7. Existing V5 team and starter Statcast features remain eligible as baseline inputs.

## Environment/catcher source contract amendment — committed before any V6 context fit

This amendment is part of the pre-fit V6 protocol. No V6 context artifact or V6 context holdout result existed when it was added.

- **Plate umpire identity:** official MLB StatsAPI live/boxscore officials only. The deprecated Statcast `umpire` column is not an admissible identity source.
- **Catcher identity:** official confirmed/projected lineup/boxscore identity where available, cross-checked against Statcast `fielder_2` in historical pitch rows. Ambiguous or missing identity blocks the context row.
- **Weather/roof:** official MLB game feed fields when posted. Historical feature construction must use the weather/roof record attached to the historical game identity; current-day values may never be written backward into older games.
- **Umpire receiving adjustment:** derived only from prior taken pitches. A frozen location/count baseline estimates expected called-strike probability; the umpire feature is a shrunk prior-only residual of actual called strikes minus baseline expectation.
- **Catcher framing adjustment:** derived from the same frozen taken-pitch baseline and is a shrunk prior-only catcher residual. It may not use postgame framing leaderboards that were not available at the target cutoff.
- **Market data:** sportsbook odds, implied probabilities, consensus, movement and closing prices remain excluded from Model_P. They enter only after the independent baseball probability exists, for no-vig comparison, EV, price limits and execution.
- **Literal consumption rule:** metadata such as `weather_consumed=true`, `umpire_consumed=true` or `catcher_consumed=true` is insufficient. Every required environment/catcher feature name must be present in the serialized model's actual feature contract or V6 scoring fails closed.

## Candidate model families

- Existing negative-binomial/score-distribution framework as baseline.
- HistGradientBoosting.
- LightGBM if dependency/runtime review passes.
- XGBoost if dependency/runtime review passes.
- Market-specific calibration/heads for ML, RL and totals.

No ensemble or model family is promoted because of in-sample fit. Selection must be temporal and predeclared.

## Evaluation design

The previously observed 2025 V5 holdout is NOT an untouched V6 holdout. It may be used only as historical research data under documented temporal walk-forward folds. V6 production promotion requires a genuinely forward evaluation window whose labels are not inspected during feature/model/threshold selection.

Historical research protocol:
- Expanding-window walk-forward folds.
- All features as-of strictly before each game.
- Calibration measured by Brier score, log loss, reliability gap and slope/intercept where supported.
- Market metrics separated by ML/RL/totals.
- Favorite/underdog and probability-tail calibration reported separately.
- No sportsbook features in Model_P.

Forward promotion protocol:
- Freeze code, features, transforms, model families, hyperparameters/selection rules, calibration method and thresholds before the forward window.
- Hash all source-derived transform artifacts and serialized models.
- Require live-feature parity and source-freshness gates.
- Require probability calibration and no catastrophic degradation versus frozen V5 baseline.
- Betting metrics are secondary to calibration and must use timestamp-valid prices.

## Missing-data policy
Required player, starter, bullpen or environment/catcher inputs do not silently default to league average unless a missingness/imputation method is trained and frozen as part of the model artifact. Otherwise the V6 context candidate is blocked. This block must not disable already-eligible V5 markets; production falls back only to the separately attested V5 model and labels V6 context as unavailable.

## Lineup policy
Confirmed lineups use exact slots. Projected lineups, if researched, must carry an explicit projection/uncertainty state and can never be represented as confirmed. The MLB-native prior-confirmed/active-roster projection is admissible as projected identity evidence, not as a confirmed lineup.

## Sportsbook independence
Odds, implied probabilities, consensus, line movement and closing prices are prohibited predictive features. They may be used only after Model_P for pricing, EV, execution and retrospective CLV analysis.

## Promotion principle
A V6 change earns production status only by beating the frozen baseline under the predeclared temporal protocol. No feature is included because another public repository uses it; public repositories are hypothesis generators and data-engineering references, not prediction sources.
