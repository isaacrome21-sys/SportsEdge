# Frozen `RUN IT` Fixture Specification

Status at drafting: `INTEGRATION_UNRUN`.

## Purpose

Define one historical MLB slate that makes the full SportsEdge execution path reproducible and auditable. The fixture is an acceptance substrate, not promotion evidence.

## Everything that must be frozen

The fixture MUST freeze every decision-relevant input, including:

- slate/game identities and scheduled first pitches,
- probable/confirmed starters and opener/bulk assignments,
- batting orders / lineup status,
- Statcast and other model feature inputs as-of the frozen pregame timestamp,
- workload / pitch-count / bullpen-availability inputs,
- weather / roof / park inputs,
- umpire/catcher inputs when present,
- model/config/artifact identity,
- **the complete market snapshot used for pricing**: book, market, side, line, American odds, availability, max stake when available, observed timestamp, and freshness metadata.

If the market snapshot is not frozen, reproducibility is not being tested because edges can change while model inputs remain identical.

## Required chain

One command must exercise the same logical chain used by a real `RUN IT` invocation:

`candidate -> distribution -> 50K simulation -> market consensus -> devig -> EV/Kelly -> executable quote -> Truth Gate -> artifact`

No stage may silently substitute today's market, today's lineups, or a current external source for the frozen fixture.

## Determinism contract

The canonical decision artifact must be byte-identical for equivalent frozen inputs.

### Test A: same-input double run

Run the full fixture twice with identical frozen inputs and seeds. Require byte-identical canonical decision output.

### Test B: irrelevant-environment variation

Repeat while varying things that must not affect the decision:

- wall-clock execution time,
- working directory,
- process ID / fresh process,
- temporary-directory path.

The canonical decision payload must remain byte-identical. Execution metadata that is intentionally noncanonical, such as a runtime timestamp, must be stored outside the canonical decision payload or otherwise excluded from the byte-identity assertion.

A failure indicates one or more of:

- unseeded/random RNG state,
- unordered iteration or nondeterministic serialization,
- current-time leakage,
- current-environment/path leakage,
- live market/source leakage,
- hidden mutable global state.

## Simulation rule

SportsEdge retains the 50K default for final probability work. Public-site 10K counts are not a design target. Fixed seeds are required for the fixture.

## Acceptance output

The fixture must expose, at minimum:

- input fixture/version hash,
- model/config/artifact hash,
- canonical quote set hash,
- simulation seed and path count,
- per-market accounted status,
- Model_P where a real engine exists,
- devig method/version,
- no-vig fair market probability,
- executable quote selected,
- EV/Kelly outputs where allowed,
- Truth Gate decision and rejection reason,
- final card artifact hash.

Full coverage means every offered market is accounted for. `NO_ENGINE` is an accounted failure state, never PASS.

## Evidence classification

- Spec committed: `PRESENT`
- Fixture command actually run on exact composed tree: `EXECUTED`
- Byte-identical output proven and preserved with hashes/logs: `EVIDENCE`

Until all three execution conditions are satisfied on the exact composed tree, integration remains `INTEGRATION_UNRUN`.
