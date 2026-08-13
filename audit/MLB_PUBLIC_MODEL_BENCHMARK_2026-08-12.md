# SportsEdge MLB public-model benchmark — 2026-08-12

This record is research input only. It does not change the frozen V5 artifact or its 2025 holdout.

## Public patterns reviewed

- ShamgarBN/mlb-bet-engine: walk-forward evaluation, LightGBM, Monte Carlo, calibration, automated retraining/self-evaluation.
- gmalbert/baseball-predictions: separate ML/RL/totals models, LightGBM/XGBoost ensembles, park/umpire/bullpen/platoon/rest context, calibration diagnostics, ROI/Sharpe/max-drawdown and Kelly tooling.
- snoozle-software/monte-carlo-mlb: explicit player/lineup Monte Carlo and projected/confirmed lineup updates; repo itself notes bullpen omission as a weakness.
- mccapobianco/pitcher-stat: event-level run expectancy using base/out state plus Statcast exit velocity and launch angle to model hit/outcome distribution.
- baseballr/Statcast schema: pitch-level release speed, spin/movement-related fields, bat speed/swing length, times-through-order and rest-day fields are available for future point-in-time feature engineering subject to chronology rules.

## SportsEdge strengths that must not be weakened

1. Predeclared temporal splits and untouched holdout discipline.
2. Frozen/hash-bound expected-contact transformer.
3. Statcast feature names must be in the serialized model feature contract; metadata alone is insufficient.
4. Sportsbook features are banned from Model_P.
5. Fail-closed missing-source, lineup, starter, artifact and price behavior.
6. Market-specific deployment state rather than all-or-nothing promotion.

## Highest-priority V6 research candidates

### A. Full lineup offense
Use batting slots 1-9 rather than only aggregate offense/top three. Candidate inputs include slot-weighted expected contact, xBA-style contact probability, barrel/hard-hit/EV, handedness and projected PA share. Projected lineups may be used only under an explicitly separate uncertainty state; confirmed orders receive exact slot binding.

### B. Bullpen state
Add prior-only reliever quality and availability: rolling contact suppression, BB/K where point-in-time safe, pitches thrown / batters faced over prior 1/2/3 days, closer/high-leverage availability proxy, and starter expected innings/third-time-through exposure. No same-day future appearances.

### C. Platoon and arsenal matchup
Add batter/pitcher handedness interaction and pitch-family matchup features from raw Statcast: pitcher pitch mix, velocity, movement/location summaries and hitter outcomes/contact quality against pitch families. Every rolling statistic must be computed strictly before game time.

### D. Park, weather and umpire as consumed features
Convert park factor, temperature, wind/roof and home-plate umpire run environment from context-only fields into actual serialized features. Point-in-time source and fallback rules must be predeclared; missing required inputs block rather than silently average unless an imputation policy is itself trained and frozen.

### E. Market-specialized ensemble
Research separate probability heads/models for MONEYLINE, RUN_LINE and TOTALS. Candidate ensemble members: Poisson/negative-binomial score model, HistGradientBoosting, LightGBM and XGBoost where licensing/runtime permits. Blend weights/calibration must be chosen without future labels and serialized/hash-bound.

### F. Walk-forward calibration and uncertainty
In addition to fixed holdouts, require season/month walk-forward evaluation, calibration slope/intercept or isotonic/Platt chosen on prior periods only, probability reliability buckets, and bootstrap/model-disagreement uncertainty. Official bet gates may require edge to exceed both transaction margin and model uncertainty.

### G. Betting evaluation separated from prediction
Track closing-line-independent calibration plus realized ROI, CLV when legitimate timestamped prices exist, Sharpe, max drawdown and Kelly sensitivity. Sportsbook prices remain post-model inputs only and are never allowed in Model_P.

## Explicitly rejected shortcuts

- Do not copy public model code or claims without reproducing/validating them in SportsEdge.
- Do not add line movement, consensus odds or implied probability to predictive features.
- Do not use today's revised historical expected-stat columns as point-in-time features.
- Do not modify V5 based on observed 2025 results and still call 2025 untouched.
- Do not add 2024+ bat-tracking fields to historical years via fabricated/imputed pseudo-history.

## Promotion rule

V5 remains frozen. Any predictive feature/model change above is a new version and requires a new predeclared evaluation protocol. Because the 2025 V5 holdout has now been observed, it cannot be reused as an untouched V6 design holdout. V6 should use historical walk-forward research and then a genuinely forward, never-before-observed evaluation window before production promotion.
