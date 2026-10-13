# Design: pre-first-pitch MLB probable-starter capture (no code yet)

Design only, for review. Goal: replace the retrospective probable-starter identity used in the Either-Pitcher walk-forward with timestamped, pre-first-pitch snapshots from the free MLB Stats API. No paid data, odds or credit-consuming collectors.

## Source
- `GET https://statsapi.mlb.com/api/v1/schedule?sportId=1&gameType=R,F,D,L,W,A,S,E&date=YYYY-MM-DD&hydrate=probablePitcher,lineups`. Include all regular, postseason (F Wild Card, D Division Series, L League CS, W World Series) and other game types; record `gameType` per row. The research cohort filter decides which types are scored, not the capture.
- Free and unauthenticated. We read `gamePk`, `gameDate` (UTC first pitch), `status.codedGameState` and `detailedState`, `teams.{away,home}.probablePitcher.id`, and `doubleHeader` / `gameNumber`.
- Optional, per game near first pitch: `GET /api/v1.1/game/{gamePk}/feed/live` (`gameData.probablePitchers`, `liveData.boxscore` once lineups post).

## Snapshot schedule (America/Chicago)
- T−24h (prior evening), T−6h, T−90m and T−30m before each game's `gameDate`, plus one final snapshot at T−5m.
- One daily sweep at 08:00 CT for the slate, and per-game snapshots keyed to `gameDate`.
- Postponements and reschedules are detected by `gameDate` and status changes between snapshots.
- Polite rate: at most 1 request per second, with backoff on 429/5xx.

## Snapshot record (append-only JSONL, one line per game per snapshot)
`{schema, gamePk, official_date, game_date_utc, captured_at_utc, minutes_to_first_pitch, status_code, away_team_id, home_team_id, away_probable_id|null, home_probable_id|null, game_number, source_url, response_sha256}`

- `captured_at_utc` comes from the capture host's clock, NTP-synced and recorded. `response_sha256` covers the raw body, which is stored compressed alongside.
- Never overwrite. A changed probable is a new line.

## As-of binding rule (for later evaluation and pricing)
- The as-of starter for a game = the latest snapshot with `captured_at_utc` < cutoff, where cutoff = first pitch − buffer. Missing either probable gives UNKNOWN, so BLOCKED.
- **Scratch and late change:** if the actual starter (from the final box score after the game) differs from the as-of probable, the event is labeled `PROBABLE_CHANGED`. Settlement treatment stays UNVERIFIED_DK_RULES, so it is excluded from grading. It is still reported in the evaluation as a void-risk count.
- Doubleheaders are keyed by `gamePk`, never by date and team.

## What a scheduled capture needs
1. **Scheduler: per-game scheduled snapshots** (revised per ChatGPT review; replaces 15-minute polling).
   - A daily planner run (~06:00 CT, re-run hourly to catch reschedules, doubleheader game 2 times and postponements) reads the schedule and writes, for each gamePk, five due times keyed to that game's current `gameDate` (first pitch): **T−24h, T−6h, T−90m, T−30m, T−5m**.
   - Tolerance windows: 24h ±30m, 6h ±15m, 90m ±10m, 30m ±5m, 5m ±2m. A snapshot taken outside its window is stored but labeled `OUT_OF_WINDOW`; it never stands in for the slot.
   - **Missed slots are recorded.** If a slot's window closes with no capture, a `MISSED` record (gamePk, slot, due_at, reason such as RUNNER_DOWN/HTTP_ERROR/RESCHEDULED) is appended. Absence is never silent.
   - If first pitch moves, slots are re-keyed to the new time. Already-taken snapshots keep their original due times and get a `RESCHEDULED_AFTER` flag.
   - T−24h slots that fall before the planner first saw the game are recorded as `MISSED:NOT_YET_SCHEDULED`.
   - Idempotent per (gamePk, slot).
2. **Storage:** an append-only store outside the repo (box disk plus periodic archive). Retention and size: about 15 games × 5 snapshots × ~30 KB per day.
3. **Integrity:** a per-file hash chain (each line includes the previous line's sha256) and a daily manifest. Clock source recorded. No retroactive edits.
4. **Monitoring:**
   - missed-slot detection: a game with fewer than 3 snapshots before first pitch is flagged CAPTURE_GAP;
   - HTTP error counts;
   - schema drift checks on required fields.
5. **Governance:** the capture writes evidence-like artifacts, so its paths and workflow need ChatGPT and freeze-inventory review before activation. Workflow changes are shared and need ChatGPT review. This doc proposes, it does not activate.
6. **Tests (when coded):**
   - parsing against recorded real responses;
   - as-of selection picks only pre-cutoff snapshots;
   - a postponed game moves slots;
   - doubleheader keyed correctly;
   - a scratch is labeled PROBABLE_CHANGED;
   - the hash chain verifies.

## Out of scope
DK offering and settlement rules, which need separate live DK rule and offering captures (#2136 ledger). Odds of any kind.

## Handoff to Muse — ChatGPT requirements (offline module + tests only)
Ownership: the capture module is assigned to **Muse**. Grok does not build it. A prototype briefly pushed in b9e2ed0 was reverted in 0e171b8, 2fe7ab4 and 353d812; Muse may read it from history or ignore it.

- **Scope:** an offline module and tests only. **No scheduler, no cron/Actions, no activation, no network calls in tests.** Output has no probabilities, prices or eligibility.
- **Snapshots:**
  - Keep all 5 per-game snapshots (T−24h, T−6h, T−90m, T−30m, T−5m), keyed to each game's current first pitch.
  - Record the **actual receipt time** (never the due time).
  - Status per slot: ON_TIME / LATE / MISSED (plus EARLY / AFTER_FIRST_PITCH). A closed slot with no receipt writes an explicit MISSED record.
- **No guarantees:** don't claim T−5 (or any slot) is guaranteed. Scheduled Actions can be delayed or dropped, so label everything best-effort.
- **Change records:** record starter changes (probable pitcher id changes between snapshots) and schedule changes (first-pitch moves, postponements, doubleheader game 2). Re-key slots to the new time.
- **Postseason:** explicit gameTypes R plus F, D, L and W (and label S, E, A). Unknown types fail closed.
- **External hash anchoring:** store a sha256 of each raw response, and anchor a chained digest **outside the editable capture file** (a separate anchor log or manifest). Verification detects edits.
- **Fail-closed identity binding:** bind by gamePk with team ids, both sides and first pitch matching. If a game is absent, duplicated, has a mismatched team or slot, or has a naive timestamp, the result is an error/UNKNOWN, never a guess.
- **Tests:** use recorded real StatsAPI responses (trimmed fixtures). Any modified copies used for change tests must be labeled as derived.
