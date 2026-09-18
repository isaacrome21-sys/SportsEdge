# EV Tracker V3 suspension doctrine

V3 is prospective-only and begins at `n=0` when it is activated on `refs/heads/main`. V1 and V2 history is immutable. No V1/V2 miss, close, attempt, disposition, or policy binding may be migrated, recomputed, deleted, or reclassified by V3.

## Anti-gaming rule

Suspension is machine-derived from acquisition-health attempt records only. Realized outcomes, CLV, ROI, win/loss, grading state, model edge, and human preference are forbidden transition inputs. There is no human SUSPENDED toggle.

Manual acquisition lanes cannot suspend. A missed manual send is a miss.

`BUDGET_RESERVE_REACHED`, zero/exhausted credits, user delay, and manual non-delivery are not provider outages. They do not stop the prospective clock.

## Provider outage

For an automated provider lane, provider-class errors are limited to authorization/forbidden, provider 5xx, timeout, and unreachable failures. The trigger is evaluated inside a frozen 30-minute window and requires at least two distinct events plus failure across all configured credential slots. Mixed runs containing a non-outage disposition do not qualify.

## State machine

`ACTIVE -> SUSPENDED` occurs only after the machine outage predicate passes. While SUSPENDED, evidence admission is refused. A successful recovery slate moves to RECOVERING. Recovery requires three consecutive slates with successful two-sided admissible closes. Every recovery observation is `NOT_EVIDENCE`. Any recovery failure returns the lane to SUSPENDED. After the third consecutive successful recovery slate, the next state is ACTIVE.

## Boundary record

Every persisted transition must bind `from_state`, `to_state`, `effective_at`, `reason_code`, current `policy_id` and `policy_sha256`, plus prior `policy_id` and `prior_policy_sha256`. This is the invalidation boundary. It does not rewrite anything on the prior side of the boundary.

This doctrine creates no Model_P, Truth Gate, promotion, staking, or OFFICIAL authority.
