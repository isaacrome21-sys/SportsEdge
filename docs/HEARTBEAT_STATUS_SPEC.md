# Heartbeat / Status Specification

Status at drafting: `INTEGRATION_UNRUN`.

## Design principle

Heartbeat monitoring is pull-based, evidence-first, and external to GitHub Actions. The question is: **has durable evidence advanced?** not **did a workflow run?**

That catches both scheduler death and persistence failure.

## Pointer write ordering

Pointer files update only after durable persistence succeeds, as a separate step after the evidence commit. The pointer must never move atomically with or before the canonical evidence write.

Required failure test: simulate durable persistence failure and assert the pointer did not advance.

## Pointer authority

The pointer is a cache. Timestamped artifacts remain canonical. If the pointer and canonical artifacts diverge, the artifacts win and the pointer is the defect.

Pointers should include a durable source path and integrity hash where available so consumers can verify that the referenced evidence exists and matches.

## Required states

- `POINTER_MISSING`
- `POINTER_UNREADABLE`
- `POINTER_SOURCE_MISSING`
- `POINTER_TIMESTAMP_UNREADABLE`
- `LANE_STALE`
- `LANE_FRESH`

Missing, unreadable, source-missing, timestamp-unreadable, and stale are distinct failure classes. Do not collapse them into generic `STALE`.

## Freshness thresholds

- Archive: 3 hours during periods when evidence is actually expected to advance.
- NRFI evidence: 36 hours.

The archive threshold must be slate-aware. A constant 3-hour clock around the entire 24-hour day would create predictable overnight false alarms and train operators to mute the monitor.

The exact active-window definition must be frozen before execution evidence is accepted.

## Detection vs delivery

Detection and delivery are separate acceptance gates.

1. **Detection:** the current stale Aug 17 state must cause the monitor to identify the lane as stale/broken according to the contract.
2. **Delivery:** the resulting alert must actually arrive through the configured user-notification path.

A check can work while delivery is broken. That is not an accepted monitor.

## Evidence-first status view

A human-facing status surface should display, per lane:

- freshness state,
- canonical latest artifact path,
- pointer state,
- latest durable timestamp,
- latest durable commit SHA if available,
- age,
- sample-count advancement where applicable,
- eligibility state separately from execution/freshness.

Freshness does not imply model eligibility.

## Status convention

- Spec/contract: `PRESENT`
- Detection test actually fires: `EXECUTED`
- Alert delivery observed: `EVIDENCE`
