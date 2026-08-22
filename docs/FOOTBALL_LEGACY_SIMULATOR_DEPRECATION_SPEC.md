# Football Legacy Simulator Deprecation Specification

Integration state: `INTEGRATION_UNRUN`.

Design only. No simulator implementation is changed by this document.

## Current migration state

The verified main-branch football generator is score-level:

- `sportsedge/core/simulate/football.py`
- `KeyNumberMarginModel`
- `JointScoreSimulator`

The current NFL directory contains adapter/history/M2/point-in-time/audit/profile plumbing, but the verified state supplied for this research session does not establish a production drive/play event-rich generator.

Therefore two generators must **not** be treated as a permanent architecture. The current score-level simulator is a legacy compatibility path until an event-rich generator exists and passes its own validation.

## Deprecation target

When the event-rich path exists:

1. Mark `JointScoreSimulator` as `LEGACY_COMPATIBILITY_ONLY`.
2. Production market read-outs must consume the event-rich joint paths.
3. The legacy generator may remain only for historical regression/compatibility comparisons; it must not silently feed production pricing.
4. No market may select between generators because one produces a more favorable edge.
5. One joint simulator per sport remains the production rule.

## Required contract test

A future production-wiring test must prove that every production football read-out receives simulation paths from the event-rich generator identity/version and rejects a legacy generator identity.

The test should cover at least:

- moneyline / win probability,
- spread / alternate spread,
- game total / alternate total,
- team totals,
- player/drive-derived read-outs once supported,
- correlated parlay/SGP read-outs.

The contract test is **BLOCKED** today because the event-rich production generator is not established in the verified current state. Writing a test against a nonexistent target and calling it executed would be false evidence.

## Migration acceptance

Legacy deprecation is complete only when all are true:

- event-rich generator code is present on the frozen branch,
- deterministic fixture execution passes,
- key-number baseline validation passes without injected 3/7 mass,
- production read-out wiring test proves the event-rich source identity,
- legacy path cannot be selected by production configuration,
- exact merge SHA and CI conclusion are verified.

## Three statuses

- PRESENT ON MAIN: **PARTIAL — legacy score-level generator is present; deprecation target is not**
- RUNTIME EXECUTED: **NO — design only**
- PRODUCING EVIDENCE: **NO**

Until the event-rich path exists, the correct status is migration design, not completed deprecation.
