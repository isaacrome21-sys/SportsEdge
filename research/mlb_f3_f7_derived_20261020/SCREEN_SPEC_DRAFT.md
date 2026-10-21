# MLB F3/F7 derived BTTS + margin — first chronological screen proposal

**DRAFT / UNFROZEN / UNRUN.** The construction, partitions, baseline, and pass rule are declared before a historical dataset or result is inspected.

## Locked construction

Use the already merged `sportsedge.period_distribution.PeriodDistribution` for 3 or 7 completed innings only, with unchanged data and empirical/m30 parameters. For first-N both-teams-to-score at integer rung K>=1, YES is the probability of `away_runs>=K and home_runs>=K`; NO is the complementary settlement. For first-N winning margin, band P is a signed-margin bucket of `home_runs-away_runs`; bands must be explicitly supplied as a **complete, non-overlapping partition** of every possible integer margin, including TIE at zero. Jeffreys 0.5 prior per complete settlement category is used as in the incumbent F5 readouts. All readouts preserve the period distribution SHA and append a versioned readout SHA. The catalog's specific F3/F7 rung offerings and bookmaker partition must be independently verified before quote binding: this construction does NOT attest DraftKings menu availability.

No new score model is fit, and no revised F3/F7 marginal is permitted inside this readout family. No sports book quote is mixed with these projections. `F3/F7` preexisting canonical deployment remains held; no registry, runner, or market eligibility change.

## Proposed screen after source admission

Target 2025 MLB regular season. Same fixture/period evidence set for candidate and chronological baseline, verified gamePk and strictly-prior complete observed-at fixture history. Reject missing/inconsistent inning source and incomplete period, duplicate gamePk, ambiguous fixture team IDs. Admit only independent pinned source manifests: a user-entered SHA alone is not authentication. For each eligible fixture and F3/F7, compare BTTS rungs 1,2,3 and frozen complete margin partition `AWAY_BY_5_PLUS,AWAY_BY_4,AWAY_BY_3,AWAY_BY_2,AWAY_BY_1,TIE,HOME_BY_1,HOME_BY_2,HOME_BY_3,HOME_BY_4,HOME_BY_5_PLUS` versus strictly-prior league-period empirical outcomes with matched Jeffreys priors; binary/multiclass Brier and log loss by game date, block-bootstrap 95% CI of candidate-minus-baseline. Flag `DOES_NOT_BEAT_BASELINE` unless both losses improve and both interval upper bounds are less than zero; `INSUFFICIENT_DATA` if paired samples or observation timestamps fail requirements. Keep all rungs and periods in report, no winner selection after seeing scores.

No closing-market quotes are present and the full DK partition is not admitted. Consequently all outputs remain `NO_MARKET_TEST`, `NOT_VALIDATED`, `eligible=false` no matter how any eventual calibration screen ends. No historical run or numeric verdict was made in this build.
