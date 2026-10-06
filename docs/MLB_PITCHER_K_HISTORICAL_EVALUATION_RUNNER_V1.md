# MLB pitcher-K historical evaluation runner v1

Status: **research only; zero betting authority**.

This runner is the execution bridge for the already-frozen pitcher-K probability candidate. It does not alter production pricing. It materializes a deterministic historical development/test sample, evaluates the candidate once on the candidate-specific 2025 test split, and emits an auditable report.

The exact sampling contract is `config/research/mlb_pitcher_k_historical_eval_plan_v1.json`. For each of 2023, 2024, and 2025, the runner uses regular-season games on June, July, August, and September dates 1, 6, 11, 16, 21, and 26. Every completed game on those dates is eligible; both actual starting pitchers are attempted. Dates are fixed before any row is materialized and no early stopping is allowed.

A row requires 5–10 strictly-prior starts, the validated opponent-K component, the validated lineup-K component when the actual starting order can be reconstructed (otherwise the existing opponent-K-only fallback), a target-date-exclusive 30-day Baseball Savant/Statcast pitcher snapshot with whiff rate/chase rate/throwing hand, and realized K/BF for the target start. Missing inputs are dropped and counted, never imputed from future data.

Historical source bytes may be cached for transport efficiency. The cache grants no forward-evidence status. Every emitted row is historical/backfill only.

The evaluator uses 2023 training, 2024 hyperparameter selection, a 2023+2024 refit, and one candidate-specific 2025 test. The 2025 readout is not broader pitcher-prop promotion evidence and cannot directly create Model_P, ACTIONABLE, staking, OFFICIAL, or bettor-facing authority.

After merge, trigger exactly one issue titled `[MLB RESEARCH] pitcher-K historical evaluation v1` with body `RUN_PITCHER_K_HISTORICAL_EVAL_V1`. The workflow posts the research-only report and uploads the materialized rows and evaluation artifact.
