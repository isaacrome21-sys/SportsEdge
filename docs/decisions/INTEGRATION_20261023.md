# Integration branch 2026-10-23 (grok/t260-integration-cleared-20261023)

Cut from main 53a636af. Local `git merge --no-ff` of independently CLEARED heads only,
for one combined owner review. Not merged to main; no PR. Everything stays SCREEN /
NOT_VALIDATED, play_allowed=false. This branch confers no validation.

## Merge order (first-parent)
1. 157f943c t255 dk-api-guard-v2 (clean) — later superseded by 491ec4c9, step 13
2. 9c2b0af3 t244 team-defense-cluster (clean)
3. 74a96052 t243 MLB pitcher coverage (conflict: rulings doc)
4. d2460d79 t235 NBA combo (clean)
5. 69ee54ec t235 NFL game scoring (clean)
6. 96dd3ef2 t235 NFL longest FG (clean)
7. f9649fa6 t257 guard v3 period (contains t249 2399e92b) (conflict: rulings doc)
8. 8c8129d0 t257 guard v3 situational (contains t247 ea53ee16) (clean)
9. ca8d8de5 t257 ledger docstring (conflicts: 4 ledger files + rulings doc)
10. 6808360c DK rendered-page fetcher (clean)
11. 56770f5c t252 ATD v1.2 dry-review (contains t236 4506dfdc) (clean)
12. 491ec4c9 t262 net-jail (descends from 157f943c via t258..t262) (clean)

## Conflict resolutions
- `docs/decisions/GROK_RULINGS_20261023.md` (add/add, at steps 3, 7, 9): kept the superset.
  At each conflict, every line of the incoming side was already present in the t255 side
  (0 missing lines), so the t255 copy was kept unchanged. After step 12 the file carries
  t262's appended sections 2026-10-23d..h. A line check confirms 0 lines are missing
  against every cleared head that has this file.
- Step 9, `config/completion_gap_policy_v1.json`, `scripts/completion_gap_ledger.py`,
  `tests/test_completion_gap_ledger_pitcher_coverage_20261023.py`,
  `research/completion_gap_ledger_20261023.json`: took the ca8d8de5 side. ca8d8de5 is the
  later cleared ledger chain (t245 -> t251 -> t257). It re-implements the 74a96052 pitcher
  coverage with SCOPE/FREEZE markers, path-escape refusal and offline mode. The committed
  ledger still matches the render (test passes). REVIEWER: confirm nothing from
  74a96052's ledger side was lost.

## Follow-up merges (after 1e354a4f was cleared)
13. f0bef78e DK fetcher lxml fix (adds lxml==6.1.3 to requirements-test.txt) (clean)
14. 03179887 t263 numpy pin (cleared 166fcc6d, plus RED e843456b and GREEN 03179887,
    which gitignore `.venv-pinned/`; those 2 commits are not yet reviewed) (clean)
15. d168f870 current main (PR #2508; it changes only prop_role_challenger.py and its test) (clean)
16. 14fae2f0 t263 venv fix (RED 4f863942, GREEN 14fae2f0): the default venv is
    ${TMPDIR:-/tmp}/sportsedge-venv-pinned and in-repo paths are refused, because an in-repo venv
    put pytest frames under the repo root, where the screen-only guard refused 55 tests. The guard
    was not loosened. (clean)
17. 6bcc8322 current main (changes only sportsedge/nfl_prop_engines_v1.py and its test) (clean)
No conflicts in 13-17.

## Checks at this head (the only counts reported)
- Venv built by the default `bash scripts/make_pinned_test_venv.sh` (/tmp/sportsedge-venv-pinned;
  numpy 2.5.3, lxml 6.1.3, nothing added by hand):
  10733 collected; 10722 passed, 11 skipped, 0 failed; 1004 subtests passed.
- All 5 period/situational screen scripts re-run with rc=0. `git status` stays clean, so the outputs are byte-identical.
- `.github/workflows/nfl-2026-line-capture.yml` is byte-identical to 53a636af and to main 6bcc8322.


## Publication
The owner declined to provide a git credential, so this branch is published *flat*
(no merge history) as grok/t265-integration-cleared-flat-20261023, cut from main 6bcc8322
through the GitHub connector with at most 4 files per push. The full merge history lives
in the git bundle at /home/box/integ/ (t260-integration.bundle, regenerated at this head).
