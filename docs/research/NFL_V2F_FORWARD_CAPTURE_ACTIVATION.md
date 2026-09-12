# NFL V2F Forward Capture Activation

Status: **BLOCKED_PENDING_EXACT_HEAD_CI_AND_CAPTURE_LAUNCHER**

This record exists to keep the V2F research candidate fail-closed while forward evidence plumbing is activated.

## Frozen candidate identity

- Preregistration commit: `5385eaa7d7f78d6fcf945df913ce8deb74c8e4a7`
- Research PR: `#389`
- Candidate id: `nfl_m2_native_score_mean_crossfit_support_v2f_candidate`
- Production registry consumption: **false**
- Promotion authority: **false**

## Forward evidence boundary

1. No game with kickoff at or before the preregistration timestamp may count as V2F prospective evidence.
2. Historical 2016-2025 results are diagnostic only and cannot be called a pristine final holdout.
3. A V2F prediction must be materialized before kickoff from strictly-as-of feature bytes and bound to an immutable candidate-code SHA plus model-artifact SHA256.
4. Decision and close quotes, when added, must be separately captured before kickoff and must match event / market / selection / threshold / book identity.
5. No reconstruction, inference, backfill, or result-derived prediction is admissible.
6. Forward V2F research state must be stored separately from the production NFL forward-CLV state. The production collector remains bound to the production M2 release and must not be reused as if V2F were deployed.
7. Source snapshots alone are useful PIT inputs but are **not** model predictions, promotion evidence, PASS, or OFFICIAL evidence.

## Activation gate

The scheduled V2F capture launcher may be activated only after the current exact research head passes its hosted CI surface. Until then, preserve the preregistration and prospective-validation contract but do not create a scheduled workflow that could silently collect under an unverified code SHA.

## Current evidence state

- genuine prospective V2F observations: **0**
- promoted V2F markets: **0**
- eligible V2F markets: **0**
- OFFICIAL V2F bets: **0**

This file does not change Model_P, Truth Gate thresholds, market eligibility, staking, or production status.
