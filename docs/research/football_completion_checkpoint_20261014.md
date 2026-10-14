# NFL / CFB completion checkpoint — 2026-10-14

This is an integration evidence record, not a model promotion or execution authorization.

## Saved repairs

- NFL interception coverage alias collision: PR #2234, exact head 800063bcfb98429cfe5f44f74d2f2256debd5e37. Three local regression tests pass. Hosted discovery/core/protection checks succeeded; NFL evidence workflow still running when this record was written. Not merged.
- CFB family scope: PR #2235, exact head c9a46cf37680d8187bb4ffd4611aa8c61b52e2cc, stacked on #2224 at 7336ceb778de8d3a90feb90fbefd3368232b2eb9. Four local tests pass. CFB team totals registered FORWARD_ONLY/NO_VALIDATION; ML/spread/total HISTORICAL/NO_VALIDATION; all remain BLOCKED. Parent registry_gate and two regression files registered. Full runtime review and current-main composition still owed.

## Independent engine test verification

Source snapshot exported from Actions run 38571769520, head 800063bcfb98429cfe5f44f74d2f2256debd5e37. Inner ZIP SHA-256 dcbea1d94ae8430e699478c9f7a05693723c6813f10af33db712d1d59ca5aa30 matched the export manifest.

31 tests passed across test_nfl_location_symmetric_g1, test_cfb_game_freeze, test_cfb_candidate_bakeoff, test_cfb_candidate_bakeoff_v2, test_cfb_candidate_bakeoff_v3 and test_cfb_dispersion_only_evaluator. These are synthetic correctness/freeze tests, not real-data model validation. No G2 attempt or new CFB evaluation was executed.

## G2 Amendment 2 document hash verification

Read the records/g2-attempt2-preregistration-20261013 branch through GitHub and independently hashed exact retrieved UTF-8 bytes. All four publication hashes match:

| File | SHA-256 |
|---|---|
| G2_ATTEMPT2_PREREGISTRATION.md | 78e0b6a63d7fbb7c160733cdd26c63addab8ea00e2ff204d740e75ae3ab8c06f |
| G2_ATTEMPT2_PREREGISTRATION_v_bb35cafc.md | bb35cafcdc34ed2d39632ebf564af2de0879daa8e4bdc90434789aa684555a70 |
| nfl_score_counts_g2_prereg_v2.json | 114b0a5d9bb1e9c8cbc6108f08ebaa0223c2e63e2e02da08aca8bfe3cb8f1ff5 |
| G2_ATTEMPT2_AMENDMENT_2.md | 88f3a84310030a1e4715cf5889fc92266253289d5a82ceb7ab0a769bbcd3be4a |

Document integrity VERIFIED. Executable integrity NOT VERIFIED: GitHub GET /commits/2f3af2a2594effa1bbaed4137516ade8e1c15422 returned 422, No commit found. The bound implementation patch 92d6d3b72529ea56e9e5a3353bd9c12b195e76205b2ab7b5972a8128150c41f6 cannot be independently derived until the exact code/base objects are published. Attempt 2 remains unspent; no execution ruling issued.

## CFB remaining evidence gap

GitHub GET /commits/bfba59f3f returned 422, No commit found. The cited candidate and its R1–R3 ratifications have not been independently bound to retrievable code in this pass. Current main cfb_game_model_freeze.json remains UNFROZEN. Do not substitute older SportsDataverse selection artifacts or synthetic fixtures for this candidate.

## Next exact actions

1. Complete #2234 exact-head evidence CI; protected merge only after all required/relevant checks succeed.
2. Independently review the complete #2224/#2235 runtime enforcement and compose with current main before protected merge.
3. Publish the exact G2 Amendment 2 code/base commits and implementation record; derive and match its patch hash, rerun the 49-case synthetic battery, then record an execution disposition.
4. Publish the full CFB candidate commit and R1–R3 records; verify their binding before any freeze/evaluation.
5. Complete Form 2 archive/capture composition and source-specific reporting-period validity independently; neither a universal 21-day nor a season-wide window proves current QB availability.

No backfill, capture/admission activation, holdout use, validation reset, invented probability or promotion occurred in this pass.

## Follow-through, 2026-10-14 08:40 CT

- #2235 completed 10/10 returned hosted checks, then merged into #2224's integration branch (NOT main), merge commit e618331e9700d648c43c307b6ac9bf3855aa2ebf. Exact branch ref independently verified at that commit. Main remains unchanged.
- Muse #2216 advanced to 7b4d503da49b164ec4fad740c86980275db368a4 with the deterministic clock repair. Independent 52-test identity battery passes; complete composed 9-module unittest battery passes 136 tests. Pytest-only archive battery is not included in that local count.
- Opened #2236, current-main Form 2 composition at a513a08a7d2ff3a840a95049c1127bef7dfaff53. All 19 implementation/test blobs copied directly from #2216's remote tree; 19 paths registered in coverage; no assertion or implementation edits. Protected/core/discovery CI running.
- Independently found an actual #2224 publication leak: ev_per_dollar and other production probability/distribution fields were absent from PRICING_KEYS. An EV-only CFB row escaped unchanged with checked=0; such scalar fields also survived as siblings of a rejected model_p.
- Opened #2237 at 51d48ef3b556e2d76ed93d264620340fa2db0e1d, stacked on e618331e. Adds 13 actual production fields to refusal/stripping; 4 tests pass, including 39 sport/field subcases, sibling stripping, nested EV refusal and NFL/MLB preservation. CI pending. Parent #2224 remains held.
- Combined new repair tests: 11 pass. With 31 existing engine tests and 136 Form 2 unittest tests, 178 distinct local tests passed. No full local pytest claim.
- NFL #2234 has 12 returned checks successful; evidence job still running (past exact-SHA M2 replay determinism, building isolated candidate diagnostics). No main merge while that relevant check remains unfinished.
- G2 code commit 2f3af2a2594effa1bbaed4137516ade8e1c15422 and CFB candidate bfba59f3f remain unavailable through GitHub. All four G2 document hashes are verified, but executable identity and validation execution remain blocked. No complete NFL/CFB model claim.

## Final saved state of this pass

- #2234: all 13 returned exact-head checks SUCCESS, including NFL evidence; protected merge succeeded into main at 8170a2e15ec77766be9df46f4b8f0867a24e7776. Main ref independently confirmed. Post-merge main CI must be followed separately; not claimed complete here.
- #2237: all 9 returned exact-head checks SUCCESS; merged into #2224 integration branch at 3fc4cdbce104d88c6094463661bec4b7108f406e (NOT main). Branch ref independently confirmed. Scope and pricing-field repairs now coexist in that parent.
- #2236: original a513a08a head completed 13/13 returned checks SUCCESS. Rebased onto the new main using all 19 exact #2216 blobs and a union manifest preserving #2234 registration; new head 55f0179c3ca15a3cd59609fb403645de5a4a2384. New exact-head CI running; PR remains draft/unmerged pending complete review and checks.
- Full NFL/CFB model completion remains blocked by the unavailable frozen executable identities described above. No real-data G2 attempt or CFB candidate run was performed. This record is a durable handoff of completed repairs and outstanding verifiable actions, not a completed model claim.
