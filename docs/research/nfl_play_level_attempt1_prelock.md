# NFL play-level game-mean candidate — Attempt 1 pre-lock

**Status:** frozen before Attempt 1 scoring. Research/shadow only.

This is Attempt 1 of the already-preregistered five-attempt
`NFL_PLAY_LEVEL_EPA_CPOE_G1` generation. It does not extend the exhausted
10-attempt box-score search and does not replace the 2026 owner.

## Objective

Test whether strictly-prior play-level football information improves the **mean**
of the frozen Attempt-9 margin and total forecasts before the already-frozen
discrete score shape is applied.

The candidate is a ridge residual correction around the frozen Attempt-9 raw
margin and total. It is deliberately **not** a new discrete-score model.
Integer 3/7 mass, integer totals, and moneyline remain owned by their existing
distribution policies.

## Frozen windows

- Development: 2016–2023 regular season.
- Research validation: 2024 regular season, one look for Attempt 1.
- Diagnostic only: 2025 regular season.
- 2026: shared/exposed shadow season only. It cannot become clean promotion
  evidence for this generation and cannot displace Attempt 9.

No historical season here is represented as a fresh final promotion holdout.

## Strict PIT feature contract

Every feature must be known strictly before target kickoff. The target game is
never included in its own rolling features.

Team form is an exponentially weighted eight-game lookback (decay 0.85 per
older game; minimum four prior team games), carrying across seasons where
necessary.

Frozen feature set:

- offense EPA/play and opponent defense EPA allowed/play;
- offense success rate and opponent success rate allowed;
- pass EPA/dropback offense/defense;
- rush EPA/rush offense/defense;
- neutral-down pass over expectation from nflverse xpass/pass-OE fields;
- offensive plays/game pace;
- starting-QB prior dropback EPA and CPOE, shrunk toward the development-only
  position-season mean with 100 pseudo-dropbacks.

A QB feature may be used only when starter identity has a point-in-time receipt
known before kickoff. Postgame participation may **not** be used to infer who
the pregame starter was. A missing PIT starter fails that candidate row closed.

Sportsbook prices, public betting, capper opinions, and closing lines are
forbidden as model features.

## Fit

Two separate ridge residual models:

- margin residual = actual home margin − frozen Attempt-9 margin mean;
- total residual = actual total − frozen Attempt-9 total mean.

Margin uses home-minus-away feature contrasts. Total uses home-plus-away feature
levels. Feature standardization is fit on each training fold only.

Ridge alpha is selected only inside 2016–2023 with expanding-season CV over the
fixed grid `[0.1, 1, 10, 100]`. Nothing from 2024, 2025, or 2026 may select
alpha or alter the feature set.

For half-point spread/total evaluation only, probability shape is a normal
residual using development-only out-of-fold residual SD. Integer lines are not
priced by this attempt.

## Attempt-1 gate on 2024

Compare Attempt 1 and frozen Attempt 9 on the identical game/market rows.

Primary metric: equal-weight mean of spread and total log loss on half-point
close lines. Closing lines are evaluation benchmarks only.

Attempt 1 passes this research gate only if all are true:

1. pooled log loss beats Attempt 9;
2. neither margin nor total log loss regresses by more than 0.002;
3. at least one of the two improves log loss by at least 0.005;
4. raw margin RMSE and total RMSE do not worsen;
5. calibration slope is 0.90–1.10, |intercept| ≤ 0.03, and ECE ≤ 0.025.

The generation's predeclared Bonferroni policy still applies across candidate
attempts.

2025 is report-only diagnostic context. It cannot rescue a 2024 failure, retune
Attempt 1, change its thresholds, or reorder the attempt budget.

## Authority

A pass means only **research challenger survives Attempt 1**. It does not create
Model_P, alter the 2026 owner, open a Truth-Gate clock, authorize staking, or
make any market OFFICIAL. A failure spends Attempt 1; Attempt 2 requires a new
pre-lock before any new scoring.
