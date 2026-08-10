# SportsEdge Production Foundation v0.1

Repo-level baseline. Run `python3 test_foundation_v0_1.py` for the full
adversarial suite (18 assertions, 7 test groups).

## What this enforces mechanically, not just documents
- Canonical team identity resolved BEFORE any classification/filter
  (the exact mechanism that would have caught the Athletics bug on day one)
- SOURCE_MANIFEST: every input carries provider + as_of + retrieved_at
- Referential integrity: a computed value with a dependency not present
  in the manifest is MISSING_LINEAGE, blocked
- SOURCE_CONFLICT: two providers disagreeing about the same fact_key is
  surfaced and blocks, never silently resolved
- Artifact hash startup check: registry-declared hashes are verified
  against actual files on disk every run; mismatch -> QUARANTINED,
  not a crash
- MODEL_STATUS (is this model validated, static) is kept structurally
  separate from BET_STATUS (is this candidate eligible right now,
  per-run) — a validated model can still produce a STALE or BLOCKED
  bet_status for a specific game.

## Files
- sportsedge_foundation_v0_1.py — core module
- test_foundation_v0_1.py — adversarial regression suite
- test_registry.json — fixture registry (contains a real artifact hash
  pointing at sportsedge_rbi_direct_v1.joblib)
- sportsedge_rbi_direct_v1.joblib — real validated artifact, used by the
  hash-verification tests (not a placeholder)
