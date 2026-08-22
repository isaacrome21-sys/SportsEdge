# Hybrid Session Execution Note — 2026-08-21

Integration state: `INTEGRATION_UNRUN`.

This note separates repository inspection, reconstructed local logic execution, and durable evidence.

## Real repository inspection

Repository source/PR metadata was read through the connected GitHub interface. No authenticated local clone was available in this session.

Verified:

- main SHA observed by recursive tree inspection: `fd656b6600a845392d4822e7237a9373b8e2539f`
- PR #96 head: `701792a8c1fb17a2aa9e900632610c0163b13491`
- #96 `sportsedge/auto_runner.py` still constructs the expanded `AutoRunReport` positionally
- #96 `sportsedge/auto_native_odds.py` uses keyword construction
- changed-file lists for #101-#108 do not touch those two files
- `scripts/archive_raw_game_odds.py` remains stdlib-only and imports nothing from `sportsedge/`

These are inspection findings, not runtime execution.

## Reconstructed local logic — V6 integrity

The adversarial tests were written first in a temporary standalone workspace. Initial expected failure:

```text
ModuleNotFoundError: No module named 'v6_integrity'
```

After implementing the standalone contract logic:

```text
......                                                                   [100%]
6 passed in 0.05s
```

Covered: post-first-pitch commit rejection, unresolved commit rejection, missing first-pitch proof, missing commit-in-push witness, delayed witness, and a valid witnessed path. Rejected/unwitnessed paths asserted zero contribution to the defined promotion aggregates.

This was **RECONSTRUCTED standalone logic**, not execution against the SportsEdge tree. It therefore does not satisfy C1/C2/C3 branch-faithful execution and produces no durable evidence.

## Reconstructed local logic — LABELRULES_V1

Tests were written first. Initial expected failure:

```text
ModuleNotFoundError: No module named 'labelrules_v1'
```

After implementing the standalone deterministic rules:

```text
........                                                                 [100%]
8 passed in 0.02s
```

Covered: completed path, player-specific workload exhaustion, UNKNOWN on unresolved competing mechanisms, declared-margin performance/tactical dominance, explicit weather, explicit injury/health, exhaustive label set, and coverage accounting.

Again, this was **RECONSTRUCTED standalone logic**, not repository execution and not evidence.

## External feasibility research

Retrosheet documentation confirms event/play data exposes substitutions, pitcher identity, score state, outs, and pitch sequence/count where known, but does not provide a general authoritative structured manager-removal reason. Injury and tactical/performance causes therefore cannot be assumed from the exit itself. See `docs/ENGINE_B_RETROSHEET_FEASIBILITY.md`.

## Status matrix

| Work | PRESENT ON MAIN | RUNTIME EXECUTED | PRODUCING EVIDENCE |
|---|---|---|---|
| A1 constructor hardening | No | No | No |
| A2 full leakage audit | Partial existing guards only | No full exact-tree grep | No |
| A3 full determinism audit | No new code | No frozen fixture | No |
| A4 archive isolation | Existing main source yes | Not rerun here | No new evidence |
| B1 runbook | No; research docs branch | No | No |
| B2 frozen fixture spec | No; research docs branch | No | No |
| C1-C3 V6 integrity implementation | No | Reconstructed standalone only: 6 passed | No |
| D1 feasibility audit | No; research docs branch | External source inspection only | No |
| D2-D3 LABELRULES/coverage | No | Reconstructed standalone only: 8 passed | No |
| D4 window/version spec | No; research docs branch | No | No |
| E backlog | No; research docs branch | No | No |
| F1 manual research set | No; research docs branch | No | No |
| F2 heartbeat refinement | No; research docs branch | No acceptance test | No |
| G1 key-number baseline | No; research docs branch | No | No |
| G2 legacy deprecation | No; research docs branch | No | No |

## Blockers

- Branch-faithful A/C/D execution: needs an authenticated real clone or Sept 1 exact composed tree; reconstructed files are insufficient for seam claims.
- A1 code hardening: explicitly blocked by the current hard freeze; do it during Sept 1 composition before integration execution.
- A2/A3/A4 complete repository-wide scans: needs real clone or reliable private code-search index.
- Archive acceptance: needs in-window execution; odds credits may remain exhausted, but `BLOCKED_NO_CREDITS` is acceptable for window-math acceptance if the pre-registered eligible count and target match.
- Heartbeat detection/delivery: acceptance tests remain unrun.
- Durable V6 evidence: Actions/execution path and forward stream must resume; historical outage is never backfilled.

Nothing in this note changes V6 gates, model math, or integration state.
