# SportsEdge UFC betting model

## Production objective
Create sportsbook-independent pre-fight probabilities, then compare against no-vig market prices for ML, distance, totals and method markets. No market price may enter the predictive feature vector.

## Data/features
- UFCStats fighter/fight history snapshots available strictly before bout time
- age, height, reach, stance, weight class
- rolling striking volume/accuracy/defense and knockdowns
- rolling takedown/submission/control rates and defense
- opponent-adjusted strength of schedule and Elo
- recent form, layoffs, camp/late-replacement flags, short notice
- scheduled rounds/title status
- missing-data indicator and uncertainty penalty

## Model stack
1. calibrated logistic baseline for interpretability
2. gradient-boosted trees/XGBoost challenger
3. Elo/recent-form prior
4. ensemble only after chronological out-of-sample validation

Public GitHub repos are research references only. Do not copy unlicensed code or accept README accuracy claims as evidence. Candidate ideas include chronological pre-fight snapshots, Elo, rolling form, XGBoost/soft-voting challengers and Kelly/EV layers.

## Validation
- chronological/walk-forward splits only
- no post-fight or future opponent leakage
- log loss + Brier score + calibration slope/intercept + reliability curves
- favorite/underdog, weight-class, gender, 3-round/5-round, debut and short-notice slices
- compare to closing no-vig baseline
- report CLV and ROI only after probability calibration passes
- untouched holdout required before official promotion

## Monte Carlo
250k outcome draws per fight from calibrated joint outcome probabilities. Outputs ML, GTD/ITD and method probabilities. Round-time simulation is a separate future layer and must not be inferred from method probabilities alone.

## Truth gate
- minimum no-vig probability edge
- positive EV threshold
- uncertainty ceiling
- market-disagreement guard for large underdog/favorite deviations
- late-replacement/missing-data penalty
- stale-price TTL
- no official method/round bet until its own holdout/calibration contract passes

## External research policy
Analyst picks/news can be used for qualitative late-breaking context (injury, replacement, weigh-in, venue) but never as direct probability features unless predeclared and historically backtested. Market odds are evaluation/pricing inputs only.
