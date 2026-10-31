# CFB operative card — Saturday Oct 31, 2026 (research record)

PAPER / 0u research record. Committed to the repo Oct 31, 2026 at the owner's
direction as the day's card build of record. This directory is the operative
build exactly as produced the night before the slate; it is not a freeze
record, starts no clock, and counts no rows toward any validation.

## Provenance

- Slate: Saturday Oct 31, 2026 FBS slate, 44 games after standing exclusions
  (Illinois college teams, Tennessee, Hawai'i @ Northern Illinois).
- Lines: DraftKings board reads captured Oct 30, 2026, 21:44–21:57 CT, one
  single-game read per game (44/44), stored verbatim in `captures/` and
  merged in `captures_all.json`. Game metadata in `game_meta.json`;
  dispatch record in `capture_dispatch_manifest.json`; intake form in
  `lines_intake_20261031.json`; slate definition in `slate_20261031.json`.
- Builder: `build_card.py` (as run). Raw engine output in
  `engine_card_raw_20261031.json` and `engine_rows_by_game.json`.

## Classification

- Every priced row passed through
  `sportsedge.lane_a_card_gates.apply_card_gates` with `current_estimate()`;
  no row was classified from raw EV.
- Gate version: `LANE_A_CARD_GATES_V3_GUARD_FAVORED_SIDE_20261029`.
- `k_used = 0` — no Lane A row headlines until the recalibration refit rule
  earns a positive k.
- Result (`card.json`, `classified_20261031.json`): 264 priced rows —
  headline 0, overconfidence bucket 40, flagged 0, excluded 186,
  blocked 38 (stale-quote). Human-readable forms: `CARD.md`, `WATCHLIST.md`.

## Grading

Graded by the nightly grade run (Sat Oct 31, 2026, 23:21 CT) against the
day's results and the lane's in-window closing captures for the same games.
