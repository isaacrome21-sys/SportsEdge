# V6 Evidence Integrity Specification

Status at drafting: `INTEGRATION_UNRUN`.

This is an integrity specification only. It does not redesign V6, alter promotion gates, or improve a model toward a threshold.

## Core chronology invariant

`generated_at <= committer_time <= remote_witnessed_at < frozen_scheduled_first_pitch < settlement_time`

Use **committer time**, not author time. Author time is user-settable and is not sufficient timing proof.

The scheduled first pitch used for eligibility MUST be frozen into the artifact pregame. Settlement must not re-fetch or replace it. A weather delay must never retroactively convert a late prediction into an eligible one.

## Remote witness — verified semantics

The integrity requirement is stronger than "a push happened nearby": the witness must establish both:

1. a GitHub-observed timestamp that is an upper bound on remote publication, and
2. proof that the exact prediction commit SHA belongs to that witnessed push.

### Important GitHub API distinction

Current GitHub Enterprise Cloud **REST Events API `PushEvent`** documentation exposes common event `created_at` plus push payload fields including `ref`, `head`, and `before`. The documented Enterprise Cloud Events API payload does **not** expose a `commits[]` array. Therefore the old combined assumption — "use Events API `created_at` and require the exact SHA to appear in that same PushEvent payload" — is not valid for an arbitrary non-head commit.

Current GitHub **push webhook** payloads do expose the pushed `commits` array (up to the documented delivery limit), while repository-webhook delivery metadata exposes `delivered_at` and the request payload. This source can prove both remote delivery time and commit membership when the exact SHA is present in the pushed-commit payload.

### Accepted witness contract

A production witness implementation must choose and version a source that can prove both properties. Preferred research contract:

- witness source: repository/GitHub-App **push webhook delivery**,
- `remote_witnessed_at`: GitHub delivery `delivered_at` (conservative upper bound),
- membership: exact prediction commit SHA is present in the webhook's pushed commit set,
- persist the delivery GUID, ref, `before`, `after`, exact matched SHA, delivery timestamp, and a hash of the witness payload.

If a future implementation uses REST Events API `created_at`, it may directly witness the target only where payload identity is sufficient (for example, target SHA equals documented `head`) or where a separately persisted GitHub compare/ancestry proof establishes membership. That is a different witness version and must not be silently treated as equivalent to "SHA appeared in payload."

Do not assume a per-commit `pushed_at` field exists.

### Retention / reconstruction constraint

GitHub documents the Events API timeline as at most 300 events and only the preceding 30 days, and notes that the Events API is not real-time. GitHub's webhook-delivery UI/documentation exposes only recent deliveries as well. Therefore witness data MUST be persisted when observed; later reconstruction is not a valid default.

If membership or remote time cannot be proven under the frozen witness version, provenance is `UNWITNESSED` and the game contributes zero promotion evidence. Do not guess.

Multi-commit pushes are acceptable only when the exact commit membership is proven. The remote witness timestamp is a conservative upper bound for the matched commit.

## Provenance states

- `WITNESSED` — eligible timing proof when all other gates pass.
- `WITNESS_DELAYED`
- `UNWITNESSED`
- `REJECTED`

There is no configurable "a few hours is okay" tolerance for promotion eligibility.

## Fail-closed rejection codes

All rejected/unverifiable rows contribute zero promotion evidence.

- `POST_FIRST_PITCH_PREDICTION_COMMIT`
- `PREDICTION_COMMIT_UNRESOLVABLE` — unverifiable, not automatically late. Track separately; a growing count is a branch-hygiene problem.
- `FIRST_PITCH_PROOF_MISSING`

A missing/unsupported remote witness is represented by provenance (`UNWITNESSED` / `WITNESS_DELAYED`) rather than retrospectively guessing timing.

## Pregame eligibility invariant

Eligibility is a **pregame property**. Settlement supplies the outcome only; it cannot alter pregame eligibility. This removes hindsight bias by construction.

## Adversarial test first

Before relying on the filter, inject a prediction that must be rejected and assert that it contributes exactly zero to all of:

- `settled_unique_games`
- V5 paired Brier
- V6 paired Brier
- V5 paired log loss
- V6 paired log loss
- calibration buckets
- every paired statistic
- the 200-game denominator

A partial rejection that removes a row from one list while leaving it in an aggregate is a failed integrity fix.

Separate adversarial cases are required for:

- `POST_FIRST_PITCH_PREDICTION_COMMIT`
- `PREDICTION_COMMIT_UNRESOLVABLE`
- `FIRST_PITCH_PROOF_MISSING`
- witness without exact commit membership
- witness at/after frozen scheduled first pitch

## Evidence boundary

The historical 53 paired observations stay separate. The Aug 17 outage gap receives **no reconstructed observations**. A restored evidence stream starts at observation #1 for the new integrity regime.

## Exclusion disclosure

Selection-bias analysis is disclosure, not a promotion gate. Log every excluded game with reason and slate context. Near the 200-eligible threshold, compare included vs excluded by:

- scheduled start-time band,
- day of week,
- park,
- doubleheader status.

If exclusions cluster, the promotion record must disclose that fact.

## Safety property

An integrity fix must not be considered successful because it makes V6 look better. If the integrity patch systematically improves the model score by changing what gets counted without a prespecified eligibility rule, treat that as a defect.

## Local prototype status

A standalone reconstructed integrity prototype was executed test-first during the research freeze. It verifies the zero-contribution invariant and exact witness-membership concept, but its generic `PushWitness` object is **not** proof that the current GitHub Events API exposes a commit array. Production integration must use the corrected witness contract above.

- PRESENT ON MAIN: **NO**
- RUNTIME EXECUTED: **LOCAL_RECONSTRUCTED_PASS — 6/6 tests**
- PRODUCING EVIDENCE: **NO**

## Status convention

- Spec on research branch: `PRESENT` on that branch only, not main.
- Adversarial test executed on exact production tree: `EXECUTED` only after branch-faithful run.
- Durable forward evidence under the integrity contract: `EVIDENCE` only after restored forward collection.

Sources verified during this research pass: GitHub Enterprise Cloud REST Event types / Events API documentation; GitHub push webhook payload documentation; repository webhook-delivery REST documentation.
