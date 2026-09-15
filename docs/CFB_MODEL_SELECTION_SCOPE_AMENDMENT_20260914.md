# CFB model-selection scope amendment — 2026-09-14

Status: EXPLICIT POLICY-INTERPRETATION AMENDMENT. This record changes no Model_P, Truth Gate threshold, promotion evidence threshold, eligibility, edge floor, staking, validation-attempt count, or OFFICIAL authority.

## Immutable surfaces reconciled

This amendment reconciles the following already-existing surfaces rather than editing their workflows or predictive code:

- `config/cfb_model_selection_policy_v1.json`, blob `e82f72f77687ca5afc1f058de11d63aa1e24a006` on main before this amendment.
- `.github/workflows/cfb-candidate-first-evaluation-readiness.yml`, blob `50a53dc0768602078a48d35a5c739b8cf5f97d20` on main before this amendment.
- PR #727 head `83531189b11ee5545ae61bf75de3cdebb96f9f18`, specifically `config/cfb_prop_participation_model_v1.json`, blob `54ee2a375d0fc58dc960e9308a6b8f4768952247`.

## 1. Chronology claim is permanently fail-closed

Repository ancestry proves the candidate-evaluation gate existed before the candidate preregistration freeze. It does **not** prove that no candidate was inspected, evaluated, or informally compared before that gate in an uncommitted notebook, local reconstruction, temporary script, or other unrecorded work.

Accordingly, the terminal chronology label for this lane is:

`PARTIALLY_PROVEN_FAIL_CLOSED`

The labels `FROZEN_BEFORE_CANDIDATE_EVALUATION` and `FROZEN_BEFORE_FIRST_EVALUATION` remain identifiers of the checked-in policy/preregistration state. They are **not** accepted as independent proof that no pre-gate exploratory evaluation occurred. Searching the repository and finding no such evaluation may not upgrade the chronology label. Positive evidence of a pre-gate evaluation, if discovered, must be recorded and may consume or otherwise affect the declared search budget according to the frozen rules.

## 2. Selection is not promotion

`config/cfb_model_selection_policy_v1.json` expressly defines a reconstructed-historical selection lane: its purpose is to choose among the preregistered candidate families using reconstructed historical data while refusing to treat those historical scores as unbiased promotion evidence.

Therefore reconstructed historical data may be used **only** for the frozen candidate-family selection exercise, subject to the existing four-attempt budget, preregistered candidate specifications, nested temporal folds, frozen primary selection metric, null-control rule, and no-post-result-retuning rules.

A family selected through that exercise begins with **NO promotion standing**. Selection cannot itself create Model_P authority, Truth Gate readiness, eligibility, staking authority, an empirical edge floor, OFFICIAL status, or admissible forward promotion evidence. Reconstructed historical results remain selection/research evidence only.

## 3. The first-evaluation workflow PIT/Truth-Gate precondition does not govern selection admission

`.github/workflows/cfb-candidate-first-evaluation-readiness.yml` currently computes `first_evaluation_allowed` as the conjunction of preregistration readiness and `historical_truth_gate_execution_allowed`. Requiring promotion-grade historical PIT/Truth-Gate readiness before candidate-family selection is a category mismatch with the frozen selection policy described above.

For **candidate-family selection admission only**, that workflow condition is superseded by this interpretation: preregistration readiness and the frozen selection-policy constraints govern whether a selection attempt may be run. A failure caused solely by absence of genuine historical promotion-grade PIT/Truth-Gate evidence may not be treated as a veto on reconstructed-historical candidate-family selection.

This is deliberately the stricter direction for promotion: it does not make reconstructed data promotion-admissible. It removes promotion-grade PIT as a prerequisite for a step that has no promotion authority, while keeping the promotion boundary entirely forward and fail-closed.

The workflow is not edited by this amendment. Its PIT/Truth-Gate outputs remain valid diagnostics for the domains they actually govern, and they may not be relabeled as selection results or forward evidence.

## 4. Relationship to PR #727 `FORWARD_CAPTURE_ONLY`

PR #727 places `point_in_time_mode: FORWARD_CAPTURE_ONLY` inside `training_source_requirements` for the CFB participation/substitution model and states that the **participation training clock** begins only with prospective immutable captures.

That clause is **not superseded, narrowed, or amended here**. It governs fitting/training of the #727 participation artifact. This amendment governs candidate-family selection scope. Reconstructed historical selection authority does not authorize reconstructed-data fitting of the #727 participation artifact.

In short: reconstructed history may choose the candidate family under the frozen selection rules; #727's participation artifact, if that PR later becomes mergeable and is otherwise authorized, must still be fit/trained only from its declared forward-capture source contract.

## 5. Independent forward holdout remains promotion evidence

The #727 requirement for an `independent_forward_holdout_strictly_after_training_snapshot` is orthogonal to candidate-family selection and remains intact. Promotion evidence must come from forward capture under the applicable frozen PIT, provenance, calibration, CLV, source-freeze, no-backfill, and evidence-binding rules.

No reconstructed row may be backfilled, relabeled as fresh, or used to satisfy that independent-forward-holdout requirement. No forward evidence may be tuned on after observation and then represented as untouched.

## Authority boundary

This amendment consumes zero candidate attempts and performs zero evaluation. It does not select a winner. It creates no Model_P, Truth Gate PASS, promotion, eligibility, staking, edge-floor, or OFFICIAL authority. Its sole purpose is to make the scope relationship explicit so selection, training, and promotion cannot silently inherit one another's evidence requirements.