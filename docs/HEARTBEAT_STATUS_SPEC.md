# Heartbeat / Status Specification

Status at drafting: `INTEGRATION_UNRUN`.

## Design principle

Heartbeat monitoring is pull-based, evidence-first, and external to GitHub Actions. The question is: **has durable evidence advanced when evidence was expected to advance?** not **did a workflow run?**

That catches both scheduler death and persistence failure without turning normal overnight quiet periods into alarms.

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

## Archive freshness — schedule-relative contract

The archive threshold is **not** a 24-hour rolling age alarm.

A durable archive advance is expected only when a declared per-game capture opportunity has occurred. For each scheduled MLB game, the obligations are the frozen target windows already used by the archive contract:

- T-180m +/-8 minutes
- T-90m +/-8 minutes
- T0 +/-8 minutes

For heartbeat purposes:

1. Build the expected target windows from the authoritative MLB schedule in America/Chicago slate context.
2. A closed target window creates an **evidence obligation**.
3. The obligation is satisfied only by a durable archive/status artifact whose timestamp corresponds to or follows that capture opportunity and whose canonical source can be verified.
4. If no target window has closed since the last satisfied obligation, the lane is schedule-relative `LANE_FRESH` even if the last artifact is more than three wall-clock hours old.
5. If an obligation remains unsatisfied for **3 hours after the target window closes**, the lane is `LANE_STALE` and alert-eligible.
6. At 4 AM CT, if no capture opportunity is outstanding, old age alone must not produce an alert.
7. A missed late-night target can still remain stale overnight; the quiet rule suppresses false alarms, not real missed obligations.

This preserves the archive's 3-hour threshold while preventing predictable nightly alerts merely because no game should be captured.

Outside-window `SKIP_OUTSIDE_CAPTURE_WINDOW` process rows may be useful operational logs, but they do **not** satisfy a missed capture obligation. Heartbeat health is evidence-first, not process-liveness-first.

## NRFI evidence freshness

NRFI/YRFI durable settlement evidence uses a 36-hour threshold because the expected cadence is one settled slate cycle rather than multiple intraday capture windows.

Freshness alone does not imply V6 eligibility. Sample growth / settled unique-game count remains visible separately.

## Detection vs delivery

Detection and delivery are separate acceptance gates.

1. **Detection:** the current stale Aug. 17 state must cause the monitor to identify an unsatisfied evidence obligation/stale lane according to the contract.
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
- latest expected evidence obligation / target window,
- whether that obligation is satisfied,
- sample-count advancement where applicable,
- eligibility state separately from execution/freshness.

Freshness does not imply model eligibility.

## Three statuses

- PRESENT ON MAIN: **NO — this refinement is on the research/docs branch; #101 remains untouched**
- RUNTIME EXECUTED: **NO — detection acceptance remains unrun**
- PRODUCING EVIDENCE: **NO — no verified alert delivery or fresh durable lane evidence**

The two acceptance gates remain independent: heartbeat detection and heartbeat delivery.
