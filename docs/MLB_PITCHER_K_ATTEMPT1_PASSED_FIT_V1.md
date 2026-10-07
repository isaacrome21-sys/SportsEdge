# MLB pitcher-K Attempt 1 passed-fit freeze v1

Status: FROZEN AFTER DEVELOPMENT PASS — FORWARD VALIDATION PENDING

Recovery run `37603403636` completed successfully on code head `245c285426db53215a6837720b80e302fcef530b` and persisted the Attempt 1 readout to data commit `26a1e4829e2d143a529e05dec2f48ee3ed6100bd`.

The preregistered development gate passed with no blockers. On the untouched 2025 candidate-test season, candidate mean RPS was `0.06369860324820355` versus incumbent `0.06738604030147184`. The pitcher-clustered 95% CI for candidate-minus-incumbent RPS was `[-0.004313509360467404, -0.0030853235244457647]`. Typical-line log loss improved from `0.5983992323990426` to `0.5861002392534086`, and ECE improved from `0.02650464241824465` to `0.011825227485733697`.

The final refit is bound to fit SHA-256 `70a31ff9b995a2d54df87feb2d51e2518fa9cd8593bf6c047970e08557b6ecea`, ridge alpha `100.0`, beta-binomial concentration `100.0`, 4,721 refit rows, and 106,681 batters faced.

Exact coefficients, means, scales, feature order, metrics, and provenance hashes are stored in `config/research/mlb_pitcher_k_attempt1_passed_fit_freeze_v1.json`.

No retraining or parameter edits are allowed before the separate prospective forward-validation protocol is frozen. Historical reconstruction does not count as prospective validation.
