# MLB pitcher-K skill formula preregistration v1

Status: **frozen before skill-candidate outcome evaluation; research only**.

This candidate does not replace the shipped pitcher-K price and does not create Model_P, staking, OFFICIAL, promotion, or bettor-facing authority.

## Formula

The candidate is a Poisson strikeout-count model. Its fixed pre-skill expectation is:

`base_lambda = recent_mean_batters_faced × recent_mean_k_per_batter_faced × opponent_factor × lineup_factor`.

Opponent context keeps the already-validated beta = 1.0 and uses `target_rel / geometric_mean(history_rel)`. If the validated announced-lineup component is present, lineup context keeps gamma = 0.5 and uses `(target_deviation / geometric_mean(history_deviation)) ** 0.5`; otherwise the frozen fallback is exactly 1.0.

The only learned skill terms are 30-day Statcast whiff rate and chase rate. They are standardized using **development-set-only** means and standard deviations. The final mean is:

`lambda = base_lambda × exp(intercept + beta_whiff*z_whiff + beta_chase*z_chase)`.

Pitcher throwing hand is retained only for calibration slicing. It is not a predictor in v1.

There are **no default coefficients**. A separately persisted `MLB_PITCHER_K_SKILL_FIT_V1` development artifact is required to calculate even a research probability.

## Development fit

Fit on 2024 and 2025 regular-season starting-pitcher rows only. Every workload/opponent/lineup/Statcast input must be constructed strictly prior to the target start. Sportsbook prices are excluded from fitting.

The three regression coefficients are fit as a Poisson GLM by deterministic IRLS from zeros, tolerance 1e-10, maximum 100 iterations. Failure to converge produces no fit artifact. Development means/stds for whiff and chase are frozen into the fit artifact.

## Untouched evaluation

Evaluation is **forward only; no backfill**. It begins with the first eligible MLB start after the development-fit artifact is merged to `main` and a main-provenance Statcast snapshot exists.

The candidate is compared with the shipped `pitcher_joint_engine` PITCHER_K probability at the same PIT timestamp. The primary metric is mean ranked probability score across half-lines 0.5 through 19.5.

A pass requires all of:

- at least 150 graded starts and 30 unique pitchers;
- the 95% pitcher-cluster bootstrap upper confidence bound for candidate-minus-baseline RPS is below zero;
- typical-line ECE at 3.5, 4.5, 5.5, and 6.5 is no worse than baseline ECE + 0.005.

Bootstrap: 2,000 reps, seed 20261006.

Passing this outcome gate still does **not** authorize an actionable betting row. A separate frozen market-price/ROI promotion gate is required before any tier or betting authority can change.
