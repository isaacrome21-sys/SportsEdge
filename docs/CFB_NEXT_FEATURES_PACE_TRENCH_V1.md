# SportsEdge CFB Next Feature Candidates V1 — Pace and Trenches

Status: **SHADOW SPEC ONLY** until `CFB_BASE_ARTIFACT_AND_VALIDATION_GATE_V1` clears.

These features may be researched and computed point-in-time, but they may not enter production `Model_P` merely because they are available or improve an in-sample fit.

## A. Pace / expected possessions candidate

### Goal
Improve the joint score distribution by modeling how many possessions and plays each team is likely to generate rather than treating scoring efficiency as independent of game volume.

### Minimal market-blind feature set
For each team, computed point-in-time and opponent-adjusted where support exists:

- neutral-situation seconds per play
- early-down seconds per play
- plays per drive
- drives per game
- neutral pass rate
- neutral rush rate
- situation-adjusted play rate excluding obvious four-minute/garbage-time states
- average drive duration
- three-and-out rate
- first-down conversion / drive-continuation rate
- opponent defensive pace interaction

Derived matchup candidates:

- expected game possessions
- expected plays for home team
- expected plays for away team
- expected pass attempts / rush attempts by team before player allocation
- pace disagreement between teams

### Point-in-time rules
- Use only games available before the target kickoff.
- No closing line, spread, total, implied probability, or market movement may influence pace state.
- Early-season values require priors; do not treat one or two games as stable team tempo.
- Coaching/system changes may alter the prior only from pregame football evidence, never from the betting market.

### Shrinkage plan
Use hierarchical partial pooling rather than raw ranks:

1. team current-season estimate
2. coach/system prior where legitimately available
3. conference/level prior
4. FBS season mean

The weight on team-specific observations grows with eligible plays/drives. Sparse early-season estimates shrink aggressively toward the higher-level prior.

Opponent interaction should be estimated from broad pace classes first. Team-vs-team cells do not receive a bespoke coefficient unless sample support is sufficient under a predeclared rule.

### Validation
Compare the frozen base model with a pace-augmented candidate on the same chronological folds. Report changes in:

- score MAE
- margin/total distribution calibration
- spread/total Brier and log loss
- fold-by-fold log-loss win rate

No promotion from in-sample score fit alone.

## B. Opponent-adjusted trench candidate

### Goal
Replace coarse OL/DL rank comparisons with football-specific, opponent-adjusted trench features that can change both expected scoring efficiency and uncertainty.

### Pass-game trench inputs
Offense:

- pressure rate allowed
- sack rate allowed
- sack-to-pressure conversion allowed
- pass-block win rate where available
- average time to pressure where available
- OL continuity / returning starts as a separate structural feature

Defense:

- pressure rate created
- sack rate
- sack-to-pressure conversion
- pass-rush win rate where available
- blitz rate and pressure-without-blitz rate where available

Derived interaction candidates:

- pass-protection vs pass-rush differential
- expected pressure-rate delta
- expected sack-rate delta

### Run-game trench inputs
Offense:

- line yards / adjusted line yards where legally sourced
- short-yardage success
- stuff rate allowed
- rushing success before/at contact where available

Defense:

- line yards allowed
- stuff rate created
- short-yardage stop rate
- defensive rushing success allowed

Derived interaction candidates:

- run-block vs front differential
- expected stuff-rate delta
- short-yardage mismatch

### Availability and replacement treatment
Personnel availability is not folded into the trench coefficient by analyst judgment. Until the validated player-impact overlay exists:

- availability/depth changes remain separate `CONTEXT_ONLY`
- the base trench feature uses observed team/unit production available before kickoff
- a missing starter may trigger a shadow sensitivity range, but not an unvalidated Model_P adjustment

### Hierarchical shrinkage
Do not use raw `OL rank x DL rank` products.

Partial-pooling hierarchy:

1. broad pass-protection/pass-rush or run-block/front class interaction
2. conference/competition-strength adjustment
3. team-unit residual
4. player-specific residual only after enough point-in-time observations exist

Sparse cells shrink toward the broad interaction prior. Any minimum-sample rule must be declared before fitting and must not be chosen after seeing performance.

### Validation
Compare the frozen pace/base candidate with a trench-augmented candidate on identical chronological folds. Report:

- home/away score MAE
- margin and total calibration
- spread/total Brier and log loss
- candidate-vs-baseline fold wins
- stability of coefficients / posterior shrinkage across seasons

A trench layer that improves one season but produces unstable interactions across folds remains shadow-only.

## C. Governance shared by both candidates

- `model_p=false` until the base gate clears and candidate OOS validation passes.
- No market-derived feature is allowed.
- External provider grades/ranks are context unless a versioned, licensed, reproducible transform is explicitly frozen.
- Missing data is `DATA_GAP`; do not impute from a betting line or third-party prediction.
- Feature definitions, source identity, observation timestamp, and transform version must be persisted so every historical row is replayable.
