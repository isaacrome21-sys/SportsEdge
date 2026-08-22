# Football Legacy Path Deprecation Specification

Integration state: `INTEGRATION_UNRUN`.

Design-only. No simulator implementation is changed by this document.

## Target architecture

SportsEdge must have one event-rich joint football generator per sport/league context, with correlated market read-outs derived from the same simulated game states. Two production generators are not an acceptable steady-state architecture.

## Legacy designation

`JointScoreSimulator` is legacy-compatibility only once the event-rich path exists. It may remain temporarily for regression comparison, migration, and historical fixture compatibility, but it must not silently remain a production source of market probabilities.

## Required production contract test

Before deprecation is complete, add a contract test that traces production read-outs and proves they consume the event-rich simulator path. The test must fail if a production read-out resolves through `JointScoreSimulator` or another score-level fallback.

Required families include at minimum moneyline, spread, total, team total, quarter/half markets where supported, and player markets that depend on shared game state.

## Migration rule

During migration, reports must identify the generator version/path used. A mixed run cannot be called fully integrated unless every production read-out has an explicit and accepted generator source.

No read-out-specific fudge factor may be used to make the legacy and event-rich generators agree.

## Key-number implication

Margins of 3 and 7 must emerge from event mechanics. The legacy score-level path must not be retained merely because it can be patched with explicit key-number masses.

## Acceptance states

- PRESENT ON MAIN: no — design spec is on the research documentation branch only
- RUNTIME EXECUTED: no
- PRODUCING EVIDENCE: no

Unblocker: event-rich football simulator exists and can be exercised in a real repository tree; then write the failing production-path contract test first and migrate consumers one by one.
