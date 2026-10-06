# MLB pitcher-K probability candidate preregistration v1

Status: **frozen before candidate scoring; research only; zero betting authority**.

This protocol is the next step after the source-complete pitcher-K skill binding. It
does not change the current production `PITCHER_K` price. It freezes one candidate
family before its outcome comparison is run.

## Candidate

The candidate predicts a starter's strikeout rate per batter faced with a
binomial-logit ridge model. The only predictors are the already-bound, pregame
features: recent BF, recent K/BF, recent pitches/BF, the validated opponent-K
index, the validated announced-lineup deviation (or neutral 1 when unavailable),
30-day Statcast whiff rate, 30-day Statcast chase rate, and throwing hand.

Projected BF is the rounded strictly-prior recent mean BF. The resulting K count
is priced with a beta-binomial distribution. No sportsbook price, fair market
probability, consensus, closing line, or outcome from the scored game is a model
input.

## PIT reconstruction

For each historical start, the 30-day Baseball Savant query ends at the official
game date and therefore excludes that game's rows and all future rows. Workload,
opponent, and lineup inputs use the same strictly-prior contracts already frozen
for the component lanes. A row missing any required source-complete input fails
closed and is counted; it is not imputed from postgame data.

## Selection boundary

- 2023: fit candidate rate models.
- 2024: choose ridge alpha and beta-binomial concentration by mean RPS.
- After that single selection, refit the rate model on 2023+2024 only.
- 2025: one candidate-specific historical test. **No 2025 tuning is allowed.**

The ridge grid is 0.1, 1, 10, 100. The beta-binomial concentration grid is
20, 50, 100, 200, and a near-binomial 1e9. Ties choose the stronger
regularization / larger concentration. Any formula change after the 2025 readout
requires a new candidate identity.

The 2025 test is not represented as fresh forward promotion evidence because
other SportsEdge pitcher-K research has already used historical 2025 games. It
can establish whether this new candidate improves the incumbent, but any broader
promotion/release authority requires a separately frozen forward protocol.

## Incumbent and metrics

The incumbent is the current `sportsedge.pitcher_joint_engine` K path using the
validated opponent-K beta=1 and lineup-K W=200, gamma=0.5 layers on the same
strictly-prior starts.

Primary metric is mean ranked probability score across half-integer K thresholds
0.5 through 19.5. Secondary metrics are typical-line log loss, 10-bin ECE at
3.5/4.5/5.5/6.5, and count MAE. The candidate-specific test requires at least
500 eligible starts. Uncertainty uses a 2,000-replicate pitcher-clustered
bootstrap with seed 20261006.

Development pass requires all of:
1. 95% CI for candidate RPS minus incumbent RPS entirely below zero.
2. Candidate typical-line ECE no worse than incumbent + 0.005.
3. Candidate typical-line log loss no worse than incumbent.

A failure is recorded as a failure. The same candidate is not retuned after
seeing 2025.

## Authority

This preregistration grants no Model_P, Truth Gate, promotion, staking, OFFICIAL,
or bettor-facing release authority. It exists to make the next model comparison
reproducible and outcome-blind at the formula-selection boundary.
