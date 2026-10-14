# PR #2190 merge-condition audit (read-only) — 2026-10-13

Head audited: `ad5084ae273bc5dba27c093a2a13cc9051d79b5f` (main `655715907` is an ancestor; 30 files, +5324/−49 vs main).
Nothing was changed on #2190. Local run: Python venv `/workspace/.venv_se`, exact head checkout.

## 1. Exact-head protected CI — MET (recorded earlier on #2090)
Both main-required checks (main-merge-hold, CFB readiness) and all 19 of #2190's own runs passed on the full SHA above.

## 2. Receipt-clock verification — MET (local, exact head)
- `tests/test_mlb_receipt_time_bounds_20261013.py` (20): `retrieved_at` is the post-fetch clock even if caller passes `now`; naive / pre-fetch-start / future / year-2000 / far-future clocks fail closed; stale replayed and duplicate receipts rejected; missing independent anchor fails closed without writing; unbounded fetch span rejected; repo-wide guard that no `sportsedge/` or `scripts/` caller passes `now=` to `fetch_schedule`.
- `tests/test_mlb_receipt_journal_replay_20261013.py` (23): restart cannot re-admit a receipt; edited / re-signed out-of-bounds / missing-field / duplicated / deleted / raw-byte-tampered journal entries fail closed; a post-game historical schedule is never as-of proof.
- `tests/test_mlb_starter_capture_clock_bounds_20261013.py` (22).
- Behavior note for reviewer: 8 shared runner callers (`archive_mlb_additional_odds`, `capture_mlb_moneyline_model_p`, `capture_mlb_pitcher_k_forward` ×2, `refresh_mlb_game_context`, `research_mlb_pitcher_prop_promotion`, `run_free_mlb_game_markets`, `run_mlb_moneyline_shadow_card`) plus 6 `sportsedge/` runners now call `fetch_schedule` without `now=`. Their own as-of logic is unchanged; only the schedule receipt stamp changes (see `docs/MLB_RECEIPT_TIME_REPLAY_REVIEW_20261013.md`).

## 3. Append-only safety tests — MET (local, exact head)
- `test_mlb_starter_capture_append_safety_20261013.py` (8), `test_mlb_starter_atomic_writes_20261013.py` (21), `test_mlb_pit_uncommitted_intent_20261013.py` (3).
- Single crash-safety mechanism: intent-journaled atomic writes in `sports/mlb/starter_capture.py` (append with pre-append chain validation, rollback on failure, capture/manifest path-collision refusal, hash-chained records). No flock variant present.
- Combined targeted run of the 12 #2190 capture/receipt/loader/parity test files: **263 passed, 628 subtests, 0 failed**.

## 4. Activation audit — MET (capture OFF, no flags flipped)
- No `.github/workflows/*` file changed by #2190. `mlb-v8-evidence.yml` remains `workflow_dispatch` only (no cron).
- Only config change: `config/reconciliation_coverage_v1.json` +1 line registering `sportsedge/sports/mlb/starter_capture.py` (governance registration, not an activation flag).
- `starter_capture.py` has no env/flag-driven enable path; its production fetcher is documented "for a future approved activation only" and nothing schedules it. Its only importer is `sportsedge/mlb_pit_binding.load_research_starter_binding` (read-only research loader), which no script, runner or workflow calls.
- No PLAY/staking/official authority added.

## Verdict
All four #2190 description conditions are satisfied on the exact head. Remaining before merge: independent (non-author) review of the 14 caller `now=` removals, and the owner's merge decision. The evidence hold for capture activation stays: merging #2190 does not activate capture; that needs its own ruling after the anchor is wired.
