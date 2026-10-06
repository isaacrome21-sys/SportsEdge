# MLB pitcher-K probability candidate implementation v1

This is the research implementation of the separately frozen probability
preregistration. It does not replace the production pitcher-K engine.

The implementation:

- extracts only the eight preregistered PIT-safe features from
  `MLB_PITCHER_K_SKILL_BOUND_CANDIDATE_V1`;
- fits an aggregated-binomial ridge-logit K/BF model;
- standardizes predictors using training rows only;
- projects BF from the strictly-prior recent mean;
- converts K/BF × projected BF into a beta-binomial count distribution;
- prices integer and half-integer K thresholds analytically;
- searches only the frozen ridge/concentration grids on validation rows;
- emits `candidate_p_over` / `candidate_p_under`, never production
  `model_p`;
- remains research-only and fail-closed on incomplete source bundles.

The historical acquisition/evaluation runner remains a separate step because it
must bind exact StatsAPI/Statcast source timing and the incumbent parity path
before consuming the candidate-specific 2025 comparison.
