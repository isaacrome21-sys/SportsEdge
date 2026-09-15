# Public-repository adoption: provider budget and preflight controls

This record documents the public implementations reviewed for SportsEdge's provider-quota controls and the exact concepts adopted. It does not grant Model_P, Truth Gate, promotion, staking, OFFICIAL, registry, evidence-clock, or backfill authority.

## Why this was required

SportsEdge observed The Odds API HTTP 401 `OUT_OF_USAGE_CREDITS` in August 2026, during the failed MLB V8 forward-holdout chain, and again in the NFL Week 2 preflight on 2026-09-14/15. The production gap was not provider error classification alone; it was the absence of a leading control that protected scarce credits before a no-backfill evidence window.

## Public sources reviewed

### `the-odds-api/samples-python`

Provider-maintained public samples treat `x-requests-remaining` and `x-requests-used` as first-class quota telemetry. The provider's V4 documentation additionally states that `GET /v4/sports/` costs zero usage credits while returning `x-requests-remaining`, `x-requests-used`, and `x-requests-last`.

Adopted:

- quota headers are control-plane state, not incidental logging;
- a zero-credit endpoint should be used for advance readiness checks;
- HTTP 200 alone is not sufficient readiness evidence.

Source-code copying: **NONE**. Repository metadata did not expose a license during this review, so SportsEdge uses only documented provider semantics and independently written code.

### `xupeng211/FootballPrediction`

License observed during review: **MIT**.

Its Stage D quota budget freezes concepts including:

- monthly quota limit;
- reserved safety buffer;
- automated spend ceiling;
- expected request cost credits;
- maximum provider requests per cycle;
- provider-reconciled quota reset with no unverified automatic reset;
- fail-closed handling when quota state is unknown.

Adopted conceptually:

- declare expected paid request cost before work;
- reserve capacity for the highest-priority evidence lane;
- prevent lower-priority automated work from spending into that reserve;
- reconcile provider-reported quota state rather than assuming calendar resets;
- fail closed when required quota telemetry is missing or malformed.

SportsEdge thresholds are independently derived from its frozen NFL capture contract rather than copied. Current confirmation capture uses two markets (`spreads`, `totals`) in one region, therefore a normal paid request costs 2 credits. The frozen 60-minute opener window at ten-minute polling allows six attempts. The 15-minute final window allows at most two attempts per game; with a conservative 16-game weekly maximum, the derived worst-case reserve is:

`(6 + 2 * 16) * 2 = 76 credits`.

Source-code copying: **NONE**. The architecture is adopted; the implementation is SportsEdge-owned Python.

### `octokit/plugin-throttling.js`

License observed during review: **MIT**.

Adopted conceptually:

- provider rate-limit/quota state is a control event distinct from ordinary application work;
- capacity exhaustion should trip a guard/circuit-breaker path rather than be treated as an ordinary downstream request failure.

Source-code copying: **NONE**.

## SportsEdge implementation boundary

The adopted controls are intentionally split:

1. **Provider budget/preflight guard** — asks whether the next frozen acquisition can be funded before the window opens.
2. **Immediate paid-request guard** — refuses lower-priority paid work that would spend into the frozen confirmation reserve.
3. **Active-window liveness guard (#733)** — independently asks whether a due opportunity actually produced a durable terminal state.

A green preflight does not prove later liveness. A liveness failure does not authorize backfill. Provider-budget metadata cannot become predictive evidence.

## Reset rule

SportsEdge must not infer that quota reset because a date, month, or billing-period label changed. A reset is usable only after provider telemetry demonstrates restored capacity. This prevents a local calendar assumption from re-enabling paid acquisition against an exhausted provider account.
