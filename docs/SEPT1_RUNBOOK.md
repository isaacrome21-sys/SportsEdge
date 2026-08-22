# Sept 1 Execution Runbook

## Purpose
Preserve the required execution order so data-loss risk is handled before merge work and each change is verified independently.

## Required order
1. **Archive capture first.** This comes before merges because archive capture is the only step that loses unrecoverable data when missed.
2. **PR #96 alone.** Execute and verify its four acceptance/regression tests as actually run. Inspection is not execution.
3. **Remaining PRs one at a time.** Do not batch-merge the stack. After each merge, verify the next seam against the new base before advancing.
4. **Expect seam breakage.** Treat failures at integration boundaries as expected evidence, not as a reason to skip verification.

## Likely seam-failure classes
The authoritative runbook should name the exact seams when available. From the preserved summary, the expected risk is at boundaries between acquisition, feature/engine wiring, pricing/devig, truth-gate decisions, artifact persistence, and stacked-branch assumptions.

## Acceptance discipline
- Archive evidence comes before code cleanup because lost capture windows cannot be reconstructed later.
- A PR is not considered verified until its required tests have executed.
- A passing lower PR does not imply the next stacked PR passes after rebasing.
- Move in dependency order and stop on the first failed seam.

## Source fidelity note
This document intentionally does not invent exact test names or seam identifiers that were not present in the available summary. Add those only by copying them from the authoritative source specification.
