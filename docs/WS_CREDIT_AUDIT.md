# WS-CREDIT paid-schedule audit

Effective scope: 2026-09-11. This is an operational budget-allocation record. It does not change any model, feature schema, candidate threshold, evidence-unit definition, close definition, promotion rule, or historical evidence.

This document records the September 11 action as taken. Later workflow activation or governance changes are separate events and do not rewrite this historical scope.

## Scheduled paid authorities after this change

- `.github/workflows/football-nfl-forward-clv-collection.yml` remains the scheduled NFL forward decision/close authority.
- `.github/workflows/ev-tracker.yml` remains scheduled because it independently grades user-selected external-EV plays and already enforces its own remaining-credit reserve.

## Parked to dispatch-only

- `archive-mlb-game-odds.yml`
- `auto-mlb.yml` paid live-machine step (push remains test-only)
- `mlb-additional-pit-archive.yml` paid archive job (push/PR remain contract-test only)
- `mlb-deadman.yml`; this must also be parked because a stale auto-MLB heartbeat would dispatch the paid archive failover
- `mlb-v8-evidence.yml`
- `mlb-v8-replay-backfill.yml`
- `nfl-2026-line-capture.yml`

The legacy NFL capture writes `data/nfl_2026_confirmation/captures`. A repository path/index audit found no second tracked file path with `nfl_2026_confirmation` in its name, and GitHub code search returned no current default-branch reference. Because GitHub code search reported incomplete indexing during this audit, this is not evidence that historical consumers never existed; it is sufficient only for the operational decision to remove its timer while preserving manual dispatch.

## Credit projection

`config/odds_api_request_projection_v3.json` intentionally distinguishes a static bound from a claim about account quota. The current NFL forward collector has a conservative regular-week request-cost bound of 98 credits under the encoded request shape (6 bulk decision clusters at 3 + up to 16 event-close requests at 5), with a 120-credit reserve plan. The EV tracker has no finite static weekly bound because accepted play count is not capped; no number is invented.

Secret values, subscription ownership, and provider terms cannot be established from repository code. Multiple configured key slots must not be treated as independent quota entitlements unless the account owner has confirmed that use is permitted.

## Evidence impact correction

**Evidence-definition impact: NONE.** This workstream does not start, reset, merge, reinterpret, or alter the definition of a Promotion Evidence V2 unit.

**Evidence-accrual opportunity: TERMINATED for the active MLB forward lane.** Parking `mlb-v8-evidence.yml` removed automatic acquisition during the already preregistered MLB 2026 forward interval. That operational change therefore affected the opportunity to accumulate evidence even though it did not change evidence semantics.

The terminal MLB audit subsequently established that the V8 lane had already failed to accrue any durable evidence units before the September 11 parking decision. The parking action therefore terminated an already non-accruing lane rather than interrupting a functioning partial sample. See `docs/MLB_2026_FORWARD_HOLDOUT_DISPOSITION.md`.

This distinction is a process correction: an operational scheduling change to an ACTIVE preregistered evidence window must record its accrual consequence even when evidence definitions remain unchanged.
