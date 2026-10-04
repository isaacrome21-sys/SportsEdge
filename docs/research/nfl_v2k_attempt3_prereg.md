# NFL V2K Attempt 3 — preregistered context-skeleton log-ratio candidate

Status: **PREREGISTERED / IMPLEMENTATION NOT FROZEN / DO NOT SCORE**

Attempt 2 is closed as a development failure. Its canonical run is 37239231204 and its frozen result is recorded in `NFL_V2K_ATTEMPT2_RESULT_V1.json`. Development budget units 1 and 2 are consumed; three remain.

Attempt 3 is candidate `NFL_V2K_CONTEXT_SKELETON_LOGRATIO_G3`. It is deliberately not a threshold retune of G2. The exposed G2 readout may motivate the *class* of structural changes, but no exposed 2021–2025 value may tune an Attempt-3 coefficient after this preregistration.

The frozen model design is:

1. Weight training drives by `2 ** (-(train_max_season - season) / 2)`, a fixed two-season half-life.
2. Build a recency-weighted context baseline by state bucket × field-position bucket with Jeffreys 0.5 smoothing for each drive outcome.
3. Estimate offense and defense effects as log outcome-rate ratios versus the recency-weighted league rate. Shrink each outcome's log ratio using a training-only empirical-Bayes variance-component reliability. Combine context, offense, defense and home effect in log space and normalize with softmax. The old additive probability-delta combination is forbidden.
4. Estimate home field directly from schedule-bound training drives as a symmetric home-vs-away drive-outcome log ratio. Scaling terminal game margin by an arbitrary divisor is forbidden.
5. For each simulated regulation game, sample one entire historical regulation drive-context skeleton from the training set using the same recency weights. Preserve drive count/order, period/clock, start field position, home/away possession side and half/game boundaries. Independent draw-count and independent field-position sampling are forbidden.
6. Compute the score-state component of the state bucket from the simulated score, not the historical skeleton score.
7. Scores arise only through TD/FG/safety/defensive-special-teams events and empirically supported conversions. No final-margin rewrite, key-number bonus mass or sportsbook feature may enter fit or simulation.

The source population and expanding walk-forward folds remain the frozen 2018–2025 REG population with 2021–2025 test folds. Market lines/prices remain evaluation-only.

The Attempt-3 root seed is performance-independent:
`SportsEdge|NFL_V2K_CONTEXT_SKELETON_LOGRATIO_G3|ATTEMPT_3|ROOT_SEED_V1`
→ SHA-256 `767e3bd4859e1a42e02daef4d89eaafdb98867badfa9b8f5be57512dfb35f3eb`
→ uint64 `8538327727501875778`.

The scored run is 50,000 paths/game. Fewer than 10,000 paths is smoke-only and may not be labeled a scored attempt.

The existing frozen acceptance gates remain unchanged: spread and total each require chronological fold-win rate ≥0.65 against the frozen market baseline plus calibration requirements; structural signed-key error must satisfy the frozen reference/tolerance and improve the frozen control metrics. Gates are conjunctive. No post-readout threshold change is permitted.

This preregistration grants no Model_P, pricing, promotion, staking, production-release, untouched-readout or OFFICIAL authority. A successor PR must implement the exact design, freeze exact code/blob identities, and explicitly set Attempt-3 scoring allowed before any scored dispatch.
