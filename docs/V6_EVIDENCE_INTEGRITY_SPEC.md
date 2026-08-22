# V6 Evidence Integrity Specification

Status at drafting: `INTEGRATION_UNRUN`.

This is an integrity specification only. It does not redesign V6, alter promotion gates, or improve a model toward a threshold.

## Core chronology invariant

`generated_at <= committer_time <= remote_witnessed_at < frozen_scheduled_first_pitch < settlement_time`

Use **committer time**, not author time. Author time is user-settable and is not sufficient timing proof.

The scheduled first pitch used for eligibility MUST be frozen into the artifact pregame. Settlement must not re-fetch or replace it. A weather delay must never retroactively convert a late prediction into an eligible one.

## Remote witness

`remote_witnessed_at` is derived from the GitHub PushEvent `created_at` that includes the relevant commit SHA in that push payload.

Do not assume a per-commit `pushed_at` field exists.

Capture the witness at push time because Events API retention is limited. Later reconstruction may legitimately produce `UNWITNESSED`; do not guess.

Multi-commit pushes are acceptable. The event timestamp is a conservative upper bound for all commits verified inside that push payload.

## Provenance states

- `WITNESSED` — eligible timing proof when all other gates pass.
- `WITNESS_DELAYED`
- `UNWITNESSED`
- `REJECTED`

There is no configurable 'a few hours is okay' tolerance for promotion eligibility.

## Fail-closed rejection codes

All rejected/unverifiable rows contribute zero promotion evidence.

- `POST_FIRST_PITCH_PREDICTION_COMMIT`
- `PREDICTION_COMMIT_UNRESOLVABLE` — unverifiable, not automatically late. Track separately; a growing count is a branch-hygiene problem.
- `FIRST_PITCH_PROOF_MISSING`

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

## Status convention

- Spec: `PRESENT`
- Adversarial test executed on exact production tree: `EXECUTED`
- Durable forward evidence under the integrity contract: `EVIDENCE`
