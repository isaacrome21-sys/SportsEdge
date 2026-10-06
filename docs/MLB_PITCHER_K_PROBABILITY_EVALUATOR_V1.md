# MLB pitcher-K probability evaluator v1

Status: **research only; zero betting authority**.

This evaluator consumes already-PIT-built pitcher-K candidate rows. It follows the
frozen candidate protocol exactly:

- fit the candidate family on 2023 rows;
- choose ridge alpha and beta-binomial concentration on 2024 mean RPS only;
- refit the selected rate model on 2023+2024;
- score the candidate-specific 2025 test once;
- compare the candidate with PIT-matched incumbent PITCHER_K probabilities across
  the frozen 0.5 through 19.5 thresholds.

The primary gate is pitcher-clustered candidate-minus-incumbent RPS with 2,000
bootstrap replicates and seed 20261006. The evaluator also enforces the frozen
typical-line log-loss and ECE conditions and the minimum 500 candidate-test starts.

Rows must carry the skill-bound candidate bundle, realized K/BF, pitcher identity,
season, and incumbent over probabilities at every frozen threshold. The incumbent
probabilities are evaluation baselines only; they are never model-fit features.

A pass remains a research-development pass only. It does not create Model_P,
promotion, staking, OFFICIAL, or bettor-facing release authority.
