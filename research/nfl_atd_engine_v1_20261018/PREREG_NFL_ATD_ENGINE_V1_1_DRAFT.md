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
- Download step: `atd_refresh.py URL DEST` fetches each file and writes a
  sidecar `<file>.fetch.json` with its sha256 and `fetched_at` taken from
  the wall clock at download. `fetched_at` is never a CLI/caller argument; a
  missing sidecar is REFRESH_FETCH_RECORD_MISSING and a sidecar whose sha256
  doesn't match the file is REFRESH_FETCH_RECORD_MISMATCH.
- Cadence (two-sided window, owner ruling): for both the stats file and the
  schedule, `captured_at − 72 h <= fetched_at <= captured_at`. Fetched after
  the entry capture ⇒ REFRESH_FETCHED_AFTER_CAPTURE; more than 72 h before ⇒
  REFRESH_STALE.
- Pricing-run time: the run's own start time (wall clock, recorded as
  `run_started_at`) must be strictly before kickoff, else RUN_AFTER_KICKOFF.
- Point-in-time (owner: 4 h buffer kept): a 2026 appearance is used only if
  its game has a result in the schedule AND kickoff + **4 h** <= entry
  `captured_at`.
- Integrity: (player_id, game_id) must be unique in the stats file; a
  duplicate ⇒ REFRESH_FAILED. A blank or "TBD" schedule gametime (or any
  unparseable gameday/gametime) ⇒ REFRESH_FAILED — the refresh does not guess
  a kickoff.
- Same construction as the calibration replay: earlier 2026 weeks enter the
  evidence window and the current-season pool exactly as earlier weeks did
  in the replay; player meta (team for the team-in-game check) updates to the
  latest included appearance.
- Run record: stats sha256, schedule sha256, fetched_at, completed-game list
  and appearance count are written to the run record **before pricing**
  (status `REFRESH_OK_PRICING_STARTED`, then `PRICED`).
- Fail closed (run refused, status `FAILED_CLOSED`, no rows priced):
  `REFRESH_MISSING`, `REFRESH_FAILED` (unreadable), `REFRESH_STALE`
  (fetch > 72 h before capture, or a completed game absent from the stats
  file), `REFRESH_FETCHED_AFTER_CAPTURE`, `REFRESH_FETCH_RECORD_MISSING`,
  `REFRESH_FETCH_RECORD_MISMATCH`, `RUN_AFTER_KICKOFF`,
  `REFRESH_SCHEDULE_MISMATCH` (stats game_id not in schedule),
  `REFRESH_TIMESTAMP_INVALID`. **There is no 2025-only fallback.**

## 2b. Server-side provenance (re-audit rulings A–G)
- Repo `isaacrome21-sys/sportsedge`. Records branch (fixed):
  `records/nfl-atd-v1-1`. Fixed paths: fetch records
  `nfl_atd_v1_1/fetch/<data sha256>.json`; run records
  `nfl_atd_v1_1/runs/<slate_id>.json`; close captures
  `nfl_atd_v1_1/closes/<season>-W<week>/<sha256 of file>.json`; settlement
  data `nfl_atd_v1_1/settlements/<season>-W<week>/<sha256>.json` (+ its
  fetch record `fetch/<sha256>.json`); verdict `nfl_atd_v1_1/VERDICT.json`.
  Close and settlement records are enumerated with the git trees API
  (`/git/trees/<tree>?recursive=1`); a truncated tree refuses
  (API_TREE_TRUNCATED).
- Access: review and pricing require `GITHUB_TOKEN` (GITHUB_TOKEN_MISSING
  otherwise). The token is never printed, logged or written to any record.
- Branch creation: the first commit on the records branch must be a dummy
  (e.g. README). A record whose commit arrived in a `branch_creation` push
  is unproven (RECORD_IN_BRANCH_CREATION), live or stored. Activity results
  are read across every page (Link pagination).
- Server-side time: the GitHub repository activity API,
  `GET /repos/{owner}/{repo}/activity`, event fields `id, before, after,
  timestamp, activity_type`, for the `push` event whose `after` is the
  record's commit. Author/committer dates are never used.
- (A) Immutable records: a record path must have exactly one commit ever
  (commits API `?path=`), with no edit, delete or re-add
  (RECORD_NOT_SINGLE_COMMIT). Its blob at that commit must equal its blob
  at the branch head (RECORD_BLOB_MISMATCH). Any `force_push` or
  `branch_deletion` activity on the records branch refuses everything
  (RECORDS_BRANCH_REWRITTEN).
- (G) One commit per push: the push event's `before` must equal the record
  commit's only parent (PUSH_NOT_SINGLE_COMMIT). Malformed or failing API
  responses are coded refusals (API_MALFORMED, API_UNAVAILABLE).
- (F) Retention: the activity API keeps roughly **90 days** of events. The
  pricer stores the raw fetch push events in the run record at run time. At
  review, a proof is a live activity match OR the stored event cross-checked
  against the commits API (its `after` = the record's single commit, its
  `before` = that commit's only parent) (STORED_EVENT_MISMATCH otherwise).
  The run record's own push must be matched live, so a slate must be
  reviewed within ~90 days of its run or it is SCREEN.
- Pricer: refuses (FAILED_CLOSED) unless the stats and schedule sha256 each
  match a proven fetch record pushed strictly before the entry capture
  (FETCH_RECORD_NOT_ON_BRANCH, FETCH_RECORD_HASH_MISMATCH,
  FETCH_PUSH_UNPROVEN, FETCH_PUSH_NOT_BEFORE_CAPTURE, …). It refuses without
  a `slate_id`. The run record holds rows, data hashes, capture/kickoff and
  the raw fetch events.
- (C) Ordering: fetch push < run-record push, and
  captured_at <= run-record push < first kickoff.
- Kickoffs: the pricer cross-checks the board kickoff against the pinned
  schedule (same teams, same instant; KICKOFF_SCHEDULE_MISMATCH refuses)
  and writes `schedule_kickoffs` into the run record. At review every priced
  row's kickoff must equal it (else the slate is SCREEN,
  ROW_KICKOFF_SCHEDULE_MISMATCH). All close windows use that row kickoff.
- Close captures: each close capture file is its own single-commit record
  named by the sha256 of its content, filed under the game's season-week.
  A close record that cannot be parsed, has no game, or is filed under the
  wrong season-week **refuses the review** (CLOSE_RECORD_UNPROVEN); a
  kickoff in it that differs from the row kickoff **refuses the review**
  (CLOSE_KICKOFF_CONFLICT). Otherwise its server push must be >= its
  `captured_at` and <= the row kickoff + **15 min**, and every entry must be
  strictly before kickoff and no later than the push. If ANY close record
  for a game fails these, every row on that game is CLV_MISSING with reason
  **CLOSE_RECORD_UNPROVEN**.
- Settlements: a settlement data record (filed under its games'
  season-week, else SETTLEMENT_MISFILED) is used only if its sha256 matches
  a fetch record (SETTLEMENT_HASH_MISMATCH, FETCH_RECORD_NOT_ON_BRANCH
  otherwise). Both the data record's own push and the fetch record's push
  must be AFTER the final (kickoff + 4 h) of the last game it covers
  (SETTLEMENT_DATA_PUSH_BEFORE_FINAL / SETTLEMENT_PUSH_BEFORE_FINAL) and
  BEFORE the review time (SETTLEMENT_PUSH_NOT_BEFORE_REVIEW). Refused files
  are listed in the verdict; their rows stay UNSETTLED. A duplicate
  (game_id, player_id) inside one record, or two used records disagreeing,
  refuse the review (SETTLEMENT_CONFLICT). The verdict reports `n_unsettled`.
- **A slate counts only if** all of the above hold on server-side times;
  otherwise it is **SCREEN** and excluded (listed as `screen_slates`).
- Recommended, owner action: branch protection on `records/*` forbidding
  force-push and deletion. Not enforceable from this code; the activity
  check above detects violations after the fact.

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
- Rule 4 CLV = implied(close Yes) − implied(entry Yes). Captures and
  settlements match on (game_id, player_id). Close = the LATEST capture
  strictly before kickoff; if it is more than 60 min before kickoff ⇒
  CLV_MISSING CLOSE_STALE; if its price is invalid ⇒ CLV_MISSING
  CLOSE_LATEST_INVALID (no fallback to an earlier capture); none ⇒
  NO_CLOSE_ROW. Raw implied, no de-vig. CLV_MISSING rows keep their win/loss.
- Rule 5 cut drift (formula owner-confirmed): per game, drift = mean CLV over
  all CLV-scored rows (picked + passed); clv_adj = clv − drift; games with
  |drift| > 0.02 flagged. Note: in a game whose scored rows are all picked,
  clv_adj sums to 0 for that game by construction, so such games contribute
  nothing to mean picked clv_adj.
- INSUFFICIENT_CLOSE_DATA (owner ruling): if more than 20% of graded picked
  rows are CLV_MISSING (all reasons together), the verdict is
  INSUFFICIENT_CLOSE_DATA. Exactly 20% does not trip.
- BEATS_MARKET iff not INSUFFICIENT_CLOSE_DATA AND picked mean CLV
  game-clustered 95% CI lower bound > 0 AND picked mean clv_adj > 0 AND
  picked mean CLV > passed mean CLV.
- Rule 6 gates: >= 4 distinct weeks AND >= 150 graded picked rows AND >= 40
  distinct games (a minimum, per the clarification memo). **One review**, at
  the first slate close where all gates are met; that accumulated sample is
  the sample of record. (B) `review()` takes slate ids only: each slate's
  rows and data hashes are read from its pushed run record at the
  records-branch head; close captures and settlements are read only from
  their proven records on the branch head (§2b). Nothing scoring-relevant
  comes from the caller: passing rows, captures or settlements raises
  TypeError. The verdict lists every close/settlement record used or
  refused, and `inputs_sha256` covers all of them. (D/E) It runs only in a
  checkout of `records/nfl-atd-v1-1` whose `origin` is
  `github.com/isaacrome21-sys/sportsedge` (RecordsLocationRefused otherwise),
  and refuses (ReviewAlreadyRecorded) if the API shows `VERDICT.json` at the
  head OR any commit ever touching that path. The verdict, with the sha256
  of the run-record contents used and their proofs, is staged create-only at
  the fixed path and **counts only once pushed** as a proven single-commit
  record. No review is rerun unless a new version preregisters it.
- CLOSE_TIMESTAMP_INVALID: any capture for that (game_id, player_id) with a
  missing or unparseable timestamp ⇒ CLV_MISSING CLOSE_TIMESTAMP_INVALID; it
  is never skipped.
- Multiple testing: a family-wise correction is a **program-level PLAY rule**
  (owner ruling), applied when PLAY eligibility is decided across families;
  it is not applied inside this family's scorer.

## 6. Owner rulings recorded (t228 delegate, Oct 22, 2026)
4 h completion buffer kept; 72 h window two-sided; >20% picked CLV_MISSING ⇒
INSUFFICIENT_CLOSE_DATA; Rule 5 formula confirmed; multiple-testing
correction is program-level. Remaining owner item: the freeze itself
(commit + tree + timestamp) — required before any row counts.
