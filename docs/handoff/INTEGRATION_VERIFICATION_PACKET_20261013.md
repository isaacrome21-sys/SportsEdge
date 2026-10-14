# Integration-lane independent verification packet (2026-10-13)

Read-only verification by Grok under owner directive t113u. **No merges, no activation.** Local pytest runs are not CI. Every PR below still needs exact-head protected CI and an independent review.
Pinned main: `655715907d101052bfc7cb3357f1442db82d8d8b`

## A. Rebuild #2174 vs composed #2190
| PR | Head | Merge-base with main | Branch-only diff |
|---|---|---|---|
| #2174 | d56c4383d1826c0d6268ca83024729b9aad90e1a | 007f323f5 (stale) | 30 files, +5311/-49 |
| #2190 | ad5084ae273bc5dba27c093a2a13cc9051d79b5f | 655715907 (current) | 30 files, +5324/-49 |

- **Blob diff:** both PRs touch the same 30 paths. 29 of the 30 are byte-identical. The one difference is `tests/test_mlb_starter_capture_20261013.py` (b76024b8 → 99122e42), from commit ad5084ae2 "exercise real production clock against prospective synthetic fixture".
- **Tests:** ran the 12 changed MLB test modules at each head.
  - #2174: **262 passed, 1 FAILED** (`ProductionPathTests::test_production_wrapper_timestamps_come_from_the_system_clock`, which raises StarterCaptureError when run against the real clock). It's a stale fixture, and #2190 fixes it.
  - #2190: **263 passed, 628 subtests passed, 0 failed.**
- **Disposition:** treat #2174 as SUPERSEDED by #2190. Keep #2190 at CODE GREEN / EVIDENCE HOLD: no external anchor, no activation, no sourced starter evidence.

## B. #2192 CFB Form2 (head b4c5ef8f8d077fbf333d1764b142907f11d88722)
- **Base mismatch.** The PR's base ref is at 655715907, but the head's merge-base is **007f323f5**. A direct tree diff against main shows phone_display.py, test_phone_display.py, test_game_quote_pair_timestamps.py, test_cfb_directory_completeness and test_injury_binding_currency as "deleted" (they're simply missing from the stale base).
- **Tests at the head:** the 7 added/modified test modules give **146 passed**.
- **Local trial merge with 655715907** (not pushed; local SHA 3cb91103):
  - The merge is clean, with auto-merges in free_models.py, run_it_full.py and free_models_phone_issue.py.
  - Branch tests plus main's phone, quote-pair, directory and currency tests: **237 passed**.
- **Recommendation:** the author should update the branch onto current main so exact-head CI runs on a tree that includes main's phone and currency work. Form2 stays `AVAILABILITY_UNVERIFIED_NO_TEAM_INJURY_REPORT`, and is never PLAY.

## C. Catalog vs registry recheck
- Rechecked against `handoff/dk_catalog_registry_audit_20261013.md` (audited at 007f323f5).
- There is **zero diff** in canonical_coverage.py and the 8 catalog/surface/deployment/#2143 files between 007f323f5 and 655715907.
- `coverage_summary()` still gives 89 registered / 39 PRICED_PATH / 50 blocked.
- All 89 (sport, market) rows match the audit CSV on state and blocker, with 0 mismatches. All 9 discrepancies listed in the audit **remain open**. The top ones for ChatGPT:
  1. CFB has no registry rows.
  2. 13 NFL props are PRICED in the registry but NO_ENGINE in the prop surface.
  3. PITCHER_HITS_WALKS_ER is PRICED while the surface says UNAVAILABLE.
  4. STOLEN_BASES is PRICED_PATH, which contradicts the owner rule NOT_OFFERED.
  5. The F5 blocker says NO_QUOTE but the real gate is eligible=false. eligible=false stays.
- No DK board was inspected, so every DK offering stays UNKNOWN.

## D. Phone cards #2117/#2118
- #2117 (head 1f606228) and #2118 (head 658f095f) are both **closed unmerged**.
- Their reconciled composition **#2176 merged** at 2026-10-13 17:37 CT and is in main 655715907 (`sportsedge/phone_display.py`, `tests/test_phone_display.py`).
- #2179 (DK opposite-side identity port) is closed.
- **Disposition:** phone-card reconciliation is DONE on main. No further action except post-merge CI confirmation.

## E. Backlog ledger extension (append to pr_backlog_triage_20261013.md)
| PR | State | Disposition |
|---|---|---|
| #2117 | closed | Superseded by #2176 (merged) |
| #2118 | closed | Superseded by #2176 (merged) |
| #2176 | merged | Phone-card composition is on main |
| #2179 | closed | Narrow port closed; covered by #2176 pairing semantics |
| #2174 | open draft | SUPERSEDED by #2190; close after #2190 is dispositioned |
| #2190 | open draft | 263/263 local; EVIDENCE HOLD (anchor) |
| #2186 | open | Replaced by #2192 |
| #2192 | open draft | Stale base; update branch, then exact-head CI |
| #2140/#2145/#2146 | open drafts | Muse CFB taxonomy; #2146 is the composition; no QB unblock |

New file: flag for ChatGPT registration.
