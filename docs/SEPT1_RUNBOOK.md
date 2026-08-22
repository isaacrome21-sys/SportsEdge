# Sept 1 Execution Runbook

## Purpose
Preserve the required execution order so data-loss risk is handled before merge work and integration is proven against the tree that will actually be merged.

## Required order
1. **Archive capture first.** This comes before merges because archive capture is the only step that loses unrecoverable data when missed.
2. **Freeze the integration base.** Record the exact base SHA before composing any PR changes.
3. **PR #96 alone.** Execute and verify its four acceptance/regression tests as actually run. Inspection is not execution. T1-T4 do not prove every `AutoRunReport` construction site is compatible with later schema changes.
4. **Do not assume a linear PR stack.** #96 and the later MLB feature/pricing branches have divergent ancestry. Do not merge branch heads merely because individual component tests are green.
5. **Compose the required PR changes onto the frozen base.** Apply the intended diffs in dependency order, preserving exact SHAs/diff identities. Stop on conflicts or semantic ambiguity.
6. **Run branch-faithful seam tests on the composed tree.** Import checks, runner tests, constructor/schema checks, pricing/devig, Truth Gate, and persistence boundaries must execute against the exact composed tree.
7. **Run the frozen-fixture acceptance test.** Freeze lineups, Statcast/features, weather/environment, workload/bullpen inputs, and the complete market/odds snapshot. Run the same fixture more than once and require an identical decision payload/card.
8. **Only after the composed tree passes, merge one logical unit at a time.** After every merge, verify that the repository still matches the proven composition or re-run the affected seam tests.

## Determinism acceptance
The frozen-fixture decision payload must be invariant to process context that is not a model input. Repeat the fixture while varying at least:

- working directory
- process ID / fresh process
- wall-clock execution time while keeping the fixture's explicit `as_of`/model clock frozen

If the decision/card changes, treat it as a determinism failure. Investigate unseeded RNG, implicit `datetime.now()`, filesystem ordering, environment-dependent paths, or nondeterministic serialization.

Timestamps that intentionally describe the execution itself may be emitted only in a non-decision envelope. They must not alter the byte-stable canonical decision payload used for the reproducibility assertion.

## PASS labels
- `COMPONENT_LOCAL_PASS` — exact component files/tests executed locally, but not proof of composition.
- `BRANCH_FAITHFUL_PASS` — tests executed against an exact branch tree.
- `INTEGRATION_PASS` — required PR changes composed onto the frozen base and seam tests executed against that exact tree.
- `INTEGRATION_UNRUN` — use this regardless of individual green component counts until the composition test executes.

Reconstructed-source execution must never be reported as branch-faithful integration evidence.

## Likely seam-failure classes
Expected risk is at boundaries between acquisition, feature/engine wiring, `AutoRunReport` schema/construction, pricing/devig, Truth Gate decisions, artifact persistence, and divergent-branch composition.

`AutoRunReport` is a named regression seam: schema changes have previously broken construction sites. Construction should be keyword-only, and tests must cover the contract separately from runner behavior.

## Acceptance discipline
- Archive evidence comes before code cleanup because lost capture windows cannot be reconstructed later.
- A PR is not considered verified until its required tests have executed.
- A passing component does not imply the composed tree passes.
- Do not interpret #96 T1-T4 as coverage of all report-construction call sites.
- Preserve the frozen base SHA, composed diff identities, model/config hashes, and fixture hash with the acceptance artifact.
- Stop on the first failed seam; do not merge forward hoping a later PR repairs it.

## Source fidelity note
This document records the discovered divergent topology and the acceptance rules derived from it. Exact historical test names or policy enumerations not present in the authoritative source remain out of scope and must not be invented.
