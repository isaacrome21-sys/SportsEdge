# MLB t117 — governance registration list (for ChatGPT)

Branch `grok/t117-mlb-generic-identity-repin-20261013`, stacked on #2202 (`grok/mlb-joint-distribution-20261013` @ 25e66a5c).
None of these paths are in `config/reconciliation_coverage_v1.json` as of this branch. Registration is ChatGPT's step; nothing here is registered, merged, activated, or eligible.

## From #2202 — 8 new files
1. `docs/MLB_GAME_MARKET_COHERENCE_AUDIT_20261013.md`
2. `docs/MLB_JOINT_TEAM_RUNS_2027_PREREG.md` (prereg; 2027 challenger NOT evaluated)
3. `docs/MLB_PITCHER_H_BB_ER_JOINT_NOTE_20261013.md`
4. `docs/proposals/MLB_GENERIC_FEATURES_SOURCE_IDENTITY_20261013.patch` (now applied by this branch; kept as the reviewed proposal record)
5. `sportsedge/mlb_source_identity.py`
6. `sportsedge/research/mlb_joint_team_runs.py`
7. `tests/test_mlb_joint_team_runs_research.py`
8. `tests/test_mlb_source_identity.py`

## From #2202 — 2 modified files (register if the exact-path check covers modified deltas)
9. `sportsedge/mlb_public_batter_history.py`
10. `sportsedge/mlb_public_pitcher_history.py`

## New in this branch
11. `sportsedge/mlb_generic_features.py` (modified: patch applied verbatim; blob 3d7d4ac7fa03c9c6c0765380a7f8602bc47f4413, equal to the patch's post-image index)
12. `config/mlb_model_surface_v1.json` (modified: re-pin of the one file above)
13. `tests/test_mlb_batter_source_identity_wiring.py` (new)
14. `docs/MLB_T117_GOVERNANCE_REGISTRATION_LIST_20261013.md` (this file)

## Re-pin record
- Procedure: the manifest pins Git blob SHA-1s that `sportsedge/mlb_model_artifact.py` recomputes; the established procedure (e.g. #1944, #1845, 067112474) updates the changed file's blob SHA in the same commit as the code change. Only `mlb_generic_features.py` changed: `d6d0947d…` -> `3d7d4ac7…` (computed with `git hash-object`). No other pin edited.
- Canonical model_artifact_sha256: `5c06c6db…c3129` -> `6d0fc4b9…c5787`. The old value is not pinned anywhere else in the repo.
- Re-pin changes provenance only; `promotion_eligible_by_artifact_alone` stays false.
