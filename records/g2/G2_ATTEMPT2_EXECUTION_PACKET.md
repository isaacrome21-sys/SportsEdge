# NFL G2 Attempt 2 — execution packet (preparation only; EXECUTION HOLD remains)

**Owner ruling 4 (Isaac, Oct 17 2026):** preparation approved, execution
HOLD remains. Finish the Amendment 2 hash reconciliation, the frozen
executable identity, the nested-sigma leakage verification and the
independent review. Preserve the unspent attempt. Return the exact final
execution packet for the GO.

**Status:** Attempt 2 is **UNSPENT**. Nothing was fit or scored, and no
real NFL data was read. The runner was invoked only to confirm that it
refuses.

## 1. Amendment 2 hash reconciliation — PASS (all published hashes recomputed from GitHub bytes)

Branch `records/g2-attempt2-preregistration-20261013`:

| File | Published SHA-256 | Recomputed |
|---|---|---|
| `config/research/nfl_score_counts_g2_prereg_v2.json` | `114b0a5d…1ff5` | `114b0a5d9bb1e9c8…` MATCH |
| `config/research/G2_ATTEMPT2_PREREGISTRATION.md` | `78e0b6a6…c06f` | `78e0b6a63d7fbb7c…` MATCH |
| `config/research/G2_ATTEMPT2_PREREGISTRATION_v_bb35cafc.md` | `bb35cafc…5a70` | `bb35cafcdc34ed2d…` MATCH |
| `config/research/G2_ATTEMPT2_AMENDMENT_2.md` | `88f3a843…be4a` | `88f3a84310030a1e…` MATCH |

The supersession chain `d5096a86… → bb35cafc… → 78e0b6a6…` is as the
package states it. The `d5096a86…` state has no retained bytes; this is a
limitation the package itself discloses.

## 2. Frozen executable identity — PASS (reconciled without the unreachable commit)

- The frozen code commit `2f3af2a2594e…` is **not on GitHub** ("not our
  ref"). It exists only in the Muse workspace.
- Its identity is defined in the prereg as base `9f8a17cd1` + the patch
  with SHA-256 `92d6d3b7…41f6`.
- Reassembling `docs/g2_attempt2_amendment2.patch.part1` + `part2` (branch
  `research/g2-attempt2-amendment2-20261013`) gives SHA-256
  **`92d6d3b72529ea56…` MATCH**.
- Applying that patch to `9f8a17cd1` produces 4 files (3,787 lines). All 4
  are **blob-identical** to the pushed GitHub implementation commit
  `95aed73c7`:
  - `scripts/run_nfl_score_counts_g2_attempt2.py`
  - `sportsedge/research/nfl_score_counts_g2_v2.py`
  - `sportsedge/research/nfl_score_counts_g2_eval_v2.py`
  - `tests/test_nfl_score_counts_g2_attempt2.py`
- **So the code on GitHub is exactly the frozen executable.** The
  nested-sigma test branch `test/g2-nested-sigma-leakage-on-2252-20261014`
  @ `83db7322c` carries the same four blobs, unchanged.

## 3. Nested-sigma leakage verification — PASS (synthetic only)

On `83db7322c` (frozen code + test-only suites): **60/60 passed**.
- 49 tests: frozen Attempt 2 battery
- 6 tests: `test_nfl_score_counts_g2_nested_sigma_leakage_20261014.py`
- 5 tests: `..._nonzero_20261014.py`

These were run in this sandbox with a minimal pytest-compatible runner,
because PyPI is blocked. The runner handles approx, raises/match, module
fixtures and tmp_path. Hosted CI remains the arbiter. The
`RuntimeWarning: divide by zero in log` lines come from `np.where`
evaluating both branches; the y = 0 branch is never selected.

**Runner refusal re-proven:** `scripts/run_nfl_score_counts_g2_attempt2.py`
raises `ATTEMPT_2_NOT_AUTHORIZED` (no go/no-go ledger at
`config/research/nfl_score_counts_g2_attempt2_go_nogo_v1.json`).

## 4. BLOCKERS to a GO-ready packet (found by this review)

1. **`BLOCKED_EXTERNAL` — the G2 source contract does not exist on
   GitHub.** The prereg binds
   `config/research/nfl_score_counts_g2_source_contract_v1.json`
   (SHA-256 prefix `79bee698`) and requires it to match before any parse.
   Every origin branch was searched, and the file is absent. This was
   first flagged Oct 13 (handoff t113/t114) and never supplied. **It
   cannot be reconstructed.** Its bytes are pinned by hash, so any
   rewrite would be a different object and a fabrication. **Needed:** the
   original file from the Muse workspace / Rocky, published byte-identical
   and checked against the full SHA-256 (only the prefix is in the prereg).
   - Related: the underlying data objects ARE reachable. The G1 source
     contract on main (`0ed8d0c0…`) pins nflverse `games.csv` @
     `be9813d1` (SHA-256 `59c8bea7…`) and the SportsEdge release
     `nfl-source-freeze-v1` (exists, published 2026-09-13).
2. **`BUILD_REQUIRES_RULING` — the frozen build contains no execution
   code.** Even with a go/no-go ledger present, the runner raises
   `ATTEMPT_2_EXECUTION_NOT_IMPLEMENTED_IN_THIS_BUILD` ("execution code is
   added only by the separately approved go/no-go step"). The prereg
   (`implementation_binding.code_change_after_this_freeze`) says new code
   is **a new implementation identity requiring a new owner ruling**. So
   the GO is really two acts:
   - (a) approve the execution-entry code (new identity, hash-bound,
     independently reviewed, synthetic-tested), then
   - (b) GO to run it once.

## 5. The exact packet Isaac would sign (once §4 is cleared)

1. G2 source contract published, full SHA-256 recorded, prefix
   `79bee698` confirmed.
2. Execution-entry code: one PR that adds only the execution path behind
   the ledger check. It cites the frozen blobs above as unchanged and
   gives a new patch SHA-256. Independent reviewer: fresh clone, synthetic
   battery green (60/60 + new tests), no real-data read in any test.
3. Exact-head hosted CI all-green on that PR.
4. The go/no-go ledger artifact
   `config/research/nfl_score_counts_g2_attempt2_go_nogo_v1.json`, naming:
   the prereg SHA-256 `78e0b6a6…`, JSON `114b0a5d…`, frozen patch
   `92d6d3b7…`, the execution-entry patch SHA-256, the source contract
   SHA-256, the confirmation string `CONSUME_SCORE_COUNTS_G2_ATTEMPT_2`,
   and Isaac's GO.
5. One run. The result is recorded whatever it is (PASS or FAIL per gate).
   Attempts remaining after that: 1.
