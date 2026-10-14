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


## F. Exact-head CI classification (t114, snapshot 2026-10-13 ~19:20 CT)

Source: GitHub check-runs API on each open PR's current head (37 open PRs updated 2026-10-13). "success" excludes skipped. Read-only; nothing rerun, merged or closed.

| PR | head | base | checks | success | failing/pending | classification |
|---|---|---|---:|---:|---|---|
| #2196 | `625b91a5` | audit/mlb-starter-current-main-verify-20261013 | 7 | 5 | pytest-discovery (pending), test (pending) | PENDING: pytest-discovery/test in progress at snapshot |
| #2195 | `86035397` | audit/mlb-starter-current-main-verify-20261013 | 9 | 7 | pytest-discovery (pending), test (pending) | PENDING: pytest-discovery/test in progress at snapshot |
| #2192 | `b4c5ef8f` | audit/cfb-form2-current-main-verify-20261013 | 9 | 9 | — | PASS (all completed checks green) |
| #2190 | `ad5084ae` | main | 24 | 20 | audit | CODE GREEN; `audit` cancelled+in-progress = superseded concurrency runs (ENVIRONMENTAL) |
| #2189 | `7650166f` | main | 12 | 12 | — | PASS (all completed checks green) |
| #2188 | `511bc57d` | audit/finish-pass-data-gaps-20261013 | 9 | 9 | — | PASS (all completed checks green) |
| #2186 | `a2cde6d1` | audit/cfb-form2-current-main-verify-20261013 | 20 | 20 | — | PASS (all completed checks green) |
| #2174 | `d56c4383` | main | 39 | 35 | — | PASS (all completed checks green) |
| #2173 | `bf26882d` | main | 23 | 21 | — | PASS (all completed checks green) |
| #2172 | `a2cde6d1` | main | 20 | 20 | — | PASS (all completed checks green) |
| #2171 | `4284238b` | main | 30 | 27 | — | PASS (all completed checks green) |
| #2170 | `07e2ce7a` | audit/mlb-starter-append-locked-20261013 | 8 | 8 | — | PASS (all completed checks green) |
| #2169 | `39f26a36` | fix/mlb-receipt-bounds-20261013 | 8 | 8 | — | PASS (all completed checks green) |
| #2168 | `157539fc` | feat/mlb-starter-capture-20261013 | 10 | 10 | — | PASS (all completed checks green) |
| #2167 | `0700b619` | feat/cfb-qb-identity-evidence-form2-20261013 | 13 | 13 | — | PASS (all completed checks green) |
| #2166 | `fd04cb55` | main | 22 | 20 | — | PASS (all completed checks green) |
| #2165 | `e79cf138` | feat/cfb-pinned-bundle-reader-20261013 | 9 | 9 | — | PASS (all completed checks green) |
| #2164 | `a20e3ebb` | feat/cfb-qb-identity-evidence-form2-20261013 | 9 | 9 | — | PASS (all completed checks green) |
| #2163 | `14be28c5` | main | 13 | 12 | main-merge-hold from the freeze-reconciliation-hold | GOVERNANCE (real, intended): main-merge-hold / freeze-reconciliation-hold — unregistered paths; stays ON HOLD |
| #2157 | `73f3fa6e` | main | 12 | 12 | — | PASS (all completed checks green) |
| #2156 | `3698cab4` | main | 12 | 12 | — | PASS (all completed checks green) |
| #2152 | `e7e334d4` | main | 14 | 12 | audit, audit | `audit` x2 cancelled = superseded concurrency (ENVIRONMENTAL); 12/12 others green |
| #2147 | `eabf3046` | main | 12 | 12 | — | PASS (all completed checks green) |
| #2146 | `b59086d5` | main | 13 | 13 | — | PASS (all completed checks green) |
| #2145 | `53a8c4c7` | main | 12 | 12 | — | PASS (all completed checks green) |
| #2140 | `19717151` | main | 13 | 13 | — | PASS (all completed checks green) |
| #2116 | `6959838a` | main | 10 | 10 | — | PASS (all completed checks green) |
| #2115 | `dcc47743` | main | 1 | 0 | audit | only check `audit` cancelled (ENVIRONMENTAL); no test run on head -> UNVERIFIED |
| #2114 | `64a50374` | main | 11 | 11 | — | PASS (all completed checks green) |
| #2113 | `b9527049` | main | 11 | 9 | pytest-discovery, test | REAL: tests/test_team_half_pricing.py::test_runner_routes_team_half_to_pricer_no_fetch (1 failed / 6415 passed) |
| #2105 | `af1a813b` | feat/canonical-run-it-20261012 | 8 | 6 | pytest-discovery, test | REAL (stale stack): collection ImportError `_validate_auto_prop_kickoffs` from scripts/run_nfl_unified_lines_card |
| #2104 | `ff5929d4` | feat/f5-quote-binding-20261012 | 10 | 8 | pytest-discovery, test | LIKELY REAL (same failing checks as #2105 on the same stale stack; log not individually read) |
| #2103 | `c6f16e1e` | feat/canonical-run-it-20261012 | 9 | 7 | test, pytest-discovery | LIKELY REAL (same failing checks as #2105 on the same stale stack; log not individually read) |
| #2097 | `2f1a8d51` | main | 1 | 1 | — | only 1 check on head (no test run) -> UNVERIFIED |
| #2084 | `8415f160` | main | 11 | 11 | — | PASS (all completed checks green) |
| #2060 | `b52a6b90` | main | 1 | 1 | — | only 1 check on head (no test run) -> UNVERIFIED |
| #1989 | `4a1255f8` | main | 13 | 13 | — | PASS (all completed checks green) |

Summary: 25 PASS; 2 ENVIRONMENTAL (cancelled concurrency: #2190, #2152); 1 GOVERNANCE hold (#2163); 4 REAL failures (#2113 team-half routing test; #2103/#2104/#2105 stale canonical-run-it stack ImportError); 2 PENDING (#2195, #2196 — new MLB fail-closed drafts on #2190's base); 3 UNVERIFIED (#2097, #2060, #2115 have no test run on head). Stacked PRs (base != main) never run the main-only freeze hold; their green does not imply main-mergeability.

## G. Phone-card final reconciliation (#2176)

- #2176 merged 2026-10-13 17:37 CT as `fbf1f13ac3cf`. Post-merge checks on that commit: 13 success, 9 skipped, 2 cancelled (superseded `audit` concurrency), 0 failures — includes `test`, `run-card`, `frozen-full-pipeline`, `contract`, `audit`.
- Current main `655715907d10`: `test`, `pytest-discovery`, `frozen-full-pipeline`, `audit` success. Scheduled ops jobs on that SHA show failures (`mlb-moneyline-durable-deadman` x2, `capture`, `nfl-durable-deadman`) — these are scheduled capture/deadman workflows, not phone-card code; classified OPERATIONAL, not a #2176 regression (not investigated further; capture stays off).
- Disposition: phone-card reconciliation CLOSED-VERIFIED on main. See section D for #2117/#2118.
