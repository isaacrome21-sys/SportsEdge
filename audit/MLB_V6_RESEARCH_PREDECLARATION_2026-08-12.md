# SportsEdge MLB V6 research predeclaration — 2026-08-12

Status: RESEARCH ONLY. V5 remains frozen.

## Objective
Test whether adding full-lineup, bullpen, platoon/arsenal, park/weather/umpire and market-specialized ensemble features improves out-of-sample calibration and betting utility without sportsbook contamination or temporal leakage.

## Candidate feature families fixed before V6 evaluation

1. Full batting order slots 1-9: prior-only expected-contact score, xBA-style contact probability, barrel rate, hard-hit rate, average exit velocity, handedness and expected PA share.
2. Starting pitcher: prior-only contact suppression, pitch mix, velocity, movement/location summaries, handedness, days rest, recent workload and times-through-order exposure proxy.
3. Bullpen: reliever aggregate prior-only quality plus prior 1/2/3-day workload and high-leverage availability proxy.
4. Platoon/arsenal: handedness interactions and hitter contact/outcome quality against pitcher pitch-family distribution.
5. Environment: park factor, temperature, wind direction/speed, roof state and umpire run environment, each with source/freshness requirements.
6. Existing V5 team and starter Statcast features remain eligible as baseline inputs.

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
- No sportsbook features in Model_P.

Forward promotion protocol:
- Freeze code, features, transforms, model families, hyperparameters/selection rules, calibration method and thresholds before the forward window.
- Hash all source-derived transform artifacts and serialized models.
- Require live-feature parity and source-freshness gates.
- Require probability calibration and no catastrophic degradation versus frozen V5 baseline.
- Betting metrics are secondary to calibration and must use timestamp-valid prices.

## Missing-data policy
Required player, starter, bullpen or environment inputs do not silently default to league average unless a missingness/imputation method is trained and frozen as part of the model artifact. Otherwise the market is BLOCKED.

## Lineup policy
Confirmed lineups use exact slots. Projected lineups, if researched, must carry an explicit projection/uncertainty state and can never be represented as confirmed.

## Sportsbook independence
Odds, implied probabilities, consensus, line movement and closing prices are prohibited predictive features. They may be used only after Model_P for pricing, EV, execution and retrospective CLV analysis.

## Promotion principle
A V6 change earns production status only by beating the frozen baseline under the predeclared temporal protocol. No feature is included because another public repository uses it; public repositories are hypothesis generators, not evidence.
