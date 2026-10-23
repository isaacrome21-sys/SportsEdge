# NFL Anytime-TD Engine v1.1 — Preregistration DRAFT (NOT FROZEN)

Status: **DRAFT, pending owner freeze.** Drafted Thu Oct 22, 2026 (CT) on
branch `grok/t227-nfl-atd-engine-fixes-20261022`. Nothing here counts until
the owner freezes a commit hash + tree hash + timestamp. v1 (`PREREG_NFL_ATD_ENGINE_V1.md`,
sha256 `c3907b08…e099`) is not edited. Status labels unchanged:
RESEARCH_ONLY / NOT_VALIDATED; nothing here opens PLAY.

Owner ruling (t228, ruling #4): the engine becomes v1.1 with a dated
current-season data rule. Thu Oct 22 board is a SCREEN. The v1.1 forward
clock starts with the first slate priced by the frozen v1.1 commit, and each
slate's run record must prove it executed that commit.

## 1. Unchanged from v1
Construction and constants: K_A = 10, 8-game half-life, last 16 appearances
(current + previous season, strictly earlier weeks), MIN_GAMES = 4, pool
POOL_MIN_GAMES = 200 with previous-season fallback for the pool only. The
2018–2025 data pins in `research/nfl_props_part2_20261018/SPEC_HASHES.txt`.
Selection, edge, settlement: locked #2399 Rules 1, 2, 3, 7, 8, 9.

## 2. (A) Current-season refresh — dated data rule
- Source: official nflverse `stats_player_week_<season>` (2026 file) plus
  nflverse `games.csv` schedule (gameday/gametime in ET).
- Cadence: one refresh per slate, fetched no more than **72 h** before the
  entry capture (fetch after capture is allowed; point-in-time still applies).
- Point-in-time: a 2026 appearance is used only if its game has a result in
  the schedule AND kickoff + **4 h** <= entry `captured_at`.
- Same construction as the calibration replay: earlier 2026 weeks enter the
  evidence window and the current-season pool exactly as earlier weeks did
  in the replay; player meta (team for the team-in-game check) updates to the
  latest included appearance.
- Run record: stats sha256, schedule sha256, fetched_at, completed-game list
  and appearance count are written to the run record **before pricing**
  (status `REFRESH_OK_PRICING_STARTED`, then `PRICED`).
- Fail closed (run refused, status `FAILED_CLOSED`, no rows priced):
  `REFRESH_MISSING`, `REFRESH_FAILED` (unreadable), `REFRESH_STALE`
  (fetch > 72 h old, or a completed game absent from the stats file),
  `REFRESH_SCHEDULE_MISMATCH` (stats game_id not in schedule),
  `REFRESH_TIMESTAMP_INVALID`. **There is no 2025-only fallback.**

## 3. Row-level fail-closed rules (t227 fixes)
Order: timing → not-a-player → price → identity → engine. Exactly one reason.
- `captured_at >= kickoff` ⇒ UNPRICED_CAPTURED_AFTER_KICKOFF; missing ⇒
  UNPRICED_TIMESTAMP_MISSING; unparseable or zone-less ⇒
  UNPRICED_TIMESTAMP_UNPARSEABLE. Accepted: ISO 8601 with offset/Z, or
  `YYYY-MM-DD H:MM AM/PM CT|ET|…`.
- yes_price must be a finite number (or numeric string) with
  100 <= |price| <= 100000; else UNPRICED_INVALID_PRICE (never a crash).
- player_id rows get the same team-in-game check as name rows:
  unknown id ⇒ UNPRICED_PLAYER_ID_UNKNOWN; latest data team not in the game
  ⇒ UNPRICED_PLAYER_TEAM_MISMATCH.

## 4. Declared UNPRICED codes (complete list; engine emits no others)
UNPRICED_INSUFFICIENT_GAMES, UNPRICED_POSITION_GROUP_NOT_POOLED,
UNPRICED_POOL_UNAVAILABLE, UNPRICED_NAME_UNRESOLVED, UNPRICED_NOT_A_PLAYER_ROW,
UNPRICED_PLAYER_ID_UNKNOWN, UNPRICED_PLAYER_TEAM_MISMATCH,
UNPRICED_INVALID_PRICE, UNPRICED_CAPTURED_AFTER_KICKOFF,
UNPRICED_TIMESTAMP_MISSING, UNPRICED_TIMESTAMP_UNPARSEABLE.
(v1 prereg declared only four; UNPRICED_POOL_UNAVAILABLE was emitted by v1
code but undeclared. Declaring them is an owner item, done by freezing this.)

## 5. (B) Forward scorer (`score_nfl_atd_forward.py`), #2399 Rules 4–6
- Rule 4 CLV = implied(close Yes) − implied(entry Yes); close = last Yes
  capture strictly before kickoff and within 60 min of it; else CLV_MISSING
  NO_CLOSE_ROW / CLOSE_STALE. Raw implied, no de-vig. CLV_MISSING rows keep
  their win/loss.
- Rule 5 cut drift: per game, drift = mean CLV over all CLV-scored rows
  (picked + passed); clv_adj = clv − drift; games with |drift| > 0.02 flagged.
- BEATS_MARKET iff picked mean CLV game-clustered 95% CI lower bound > 0 AND
  picked mean clv_adj > 0 AND picked mean CLV > passed mean CLV.
- Rule 6 gates: >= 4 distinct weeks AND >= 150 graded picked rows AND >= 40
  distinct games (a minimum, per the clarification memo). **One review**, at
  the first slate close where all gates are met; that accumulated sample is
  the sample of record; later rows never enter it and no review is rerun
  unless a new version preregisters it (scorer raises ReviewAlreadyRecorded).

## 6. Open owner items
1. Freeze (commit + tree + timestamp) — required before any row counts.
2. Confirm the 4 h completion buffer and 72 h refresh bound.
3. Confirm Rule 5 operationalisation (mean-CLV drift, 0.02 flag) — #2399
   names the check but not its formula.
4. Whether an INSUFFICIENT_CLOSE_DATA trip (as in Part 2) applies; #2399
   doesn't state one, so none is implemented — missing-close counts are reported.
5. Multiple-testing correction across families (not in #2399).
