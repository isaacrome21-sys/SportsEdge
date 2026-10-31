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

**NOT YET GRADED at the Saturday Oct 31 morning point-in-time audit.**
The original pregame record in merge commit `2ecb6fa4b7ea55647b379d0df3d5129545421331`
prematurely asserted a Sat Oct 31 23:21 CT nightly grade before that time
had occurred. That assertion is not evidence of grading or closing captures;
see integrity issue #2974. The original bytes remain available in the
historical commit. Any later postgame grade must be separately timestamped,
source-bound to final results and authenticated same-market closing receipts,
and reviewed prospectively; it must not alter this pregame record or confer
retroactive counted/CLV/verification authority. Until then: NO GRADE,
NO AUTHENTICATED CLOSE, NO FORWARD COUNT, PAPER / 0u / NO PLAY.
