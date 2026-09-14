# Freeze reconciliation hard stop

Issue #686 is a fail-closed repository state, not a semantic label applied to selected pull requests.

## Main hold

While `config/freeze_reconciliation_policy_v1.json` is `ACTIVE_BLOCKED`, every pull request to `main` is deferred regardless of whether it appears to be plumbing, research-only, zero-authority, documentation, model work, or evidence/governance work. The only process exception is the exact reconciliation branch named in that policy. This avoids deciding whether a merge is evidence-semantic only after it has already changed the reconciliation target.

The Actions workflow makes this rule visible and automatically fails other PRs. **It is not an unbypassable GitHub server-side lock by itself.** Repository branch protection/rulesets must mark the check required to prevent a manual merge at the GitHub layer. Until that is configured, the unconditional hold also remains a process rule.

## Delta x bundle matrix

Reconciliation is recorded as one row for every registered merge delta and every registered active freeze bundle. A combined-head verdict is not sufficient.

Each row has exactly one state:

- `NOT_APPLICABLE` — the delta was already included when that bundle was frozen, or it has no intersection with the bundle's explicitly declared coverage.
- `MATCH` — the delta intersects the declared coverage but deterministic replay proves the covered file inventory and bytes are unchanged.
- `PROVISIONAL_DRIFT_BLOCKED` — provenance or replay is unavailable, so no terminal statement can be made.
- `DRIFT_CONFIRMED` — deterministic before/after replay proves covered bytes or covered inventory changed.

`DRIFT_CONFIRMED` is terminal for the row. It must never be represented as pending merely because the bundle-level consequence has not yet been applied.

The delta identity includes the merge SHA, its first parent and exact changed path list. Bundle snapshots hash the sorted covered path inventory and each file's SHA-256. Adding or deleting a file under declared coverage is therefore drift just like changing bytes in an existing file.

## Consequence of confirmed drift

Any bundle with one or more `DRIFT_CONFIRMED` rows must receive one explicit terminal disposition before the main hold can lift:

### REFROZEN

A re-freeze requires:

- a new bundle identity;
- the exact new freeze SHA;
- a new forward-evidence clock start timestamp;
- the new freeze to descend from the prior freeze.

Evidence from the old forward clock does not silently carry across the invalidated freeze.

### REVOKED

A revocation requires:

- an explicit revocation timestamp;
- `prior_forward_clock_invalidated=true`.

A successor freeze, if one is later created, starts its own forward clock. Revocation is not `EVIDENCE_PENDING` and not `PROVISIONAL_DRIFT_BLOCKED`.

## Release conditions

The hold cannot be released unless all of the following are true:

1. the active-freeze inventory has been explicitly marked complete;
2. every delta x bundle row is terminal;
3. every drifted bundle is refrozen or revoked;
4. every re-frozen bundle has a new SHA and forward-clock epoch;
5. current `main` is exactly the head through which reconciliation was performed;
6. reconciliation grants no Model_P, Truth Gate, promotion, staking, OFFICIAL, validation-attempt, or untouched-readout authority.

If `main` advances after reconciliation, the state becomes blocked again and the new merge must be appended as a separate delta. Previous rows remain interpretable; they are not collapsed into a new combined-head judgment.

## Current registry state

The initial registry includes every known merge after the #686 baseline and includes the currently identified NFL V2J/V2K, CFB historical-market archive, market-maker radar, global promotion-evidence, and MLB DFS evidence bundles. `bundle_inventory_complete` is deliberately `false` until the repository-wide active-freeze inventory is audited. This is a hard release blocker, not an invitation to guess omitted bundles.

Run locally with full git history:

```bash
python scripts/reconcile_freeze_deltas.py \
  --current-main-ref origin/main \
  --output artifacts/governance/freeze_reconciliation_report.json
```

Use `--require-release-ready` only when attempting to prove that the stop can be lifted. It exits nonzero while any release blocker remains.
