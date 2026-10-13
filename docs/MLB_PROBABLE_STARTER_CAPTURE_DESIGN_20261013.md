# Design: pre-first-pitch MLB probable-starter capture (no code yet)

Design only, for review. Goal: replace the retrospective probable-starter identity used in the Either-Pitcher walk-forward with timestamped, pre-first-pitch snapshots from the free MLB Stats API. No paid data, odds or credit-consuming collectors.

## Source
- `GET https://statsapi.mlb.com/api/v1/schedule?sportId=1&gameType=R&date=YYYY-MM-DD&hydrate=probablePitcher,lineups`
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
1. **A scheduler:** a GitHub Actions cron, or a box cron/systemd timer, running every 15 minutes during the 10:00–23:59 CT window. It computes which games are due for a snapshot and is idempotent per (gamePk, snapshot slot).
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
