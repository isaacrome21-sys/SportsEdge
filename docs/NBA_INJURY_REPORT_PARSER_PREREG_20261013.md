# Pre-registration: offline, forward-only NBA official injury-report parser

Committed before the parser code. **Governance flag:** this is a new pre-registration path and needs ChatGPT freeze-inventory registration. Research only. No scheduler, no activation, no network calls, and **no retrospective backfill for evaluation**. Historical PDFs are used only as parser test fixtures.

## Input
- The text of an official NBA injury-report PDF extracted with `pdftotext -layout` (poppler). The extractor name and version are recorded.
- The sha256 of the original PDF bytes and the **source receipt time** (when we fetched it), kept separately from the report's effective time.

## Fixed behavior
1. **Effective time** comes only from the report header `Injury Report: MM/DD/YY HH:MM AM|PM`, interpreted as America/New_York and stored in UTC.
   - The filename time is ignored (it is often 30 minutes earlier than the header).
   - Pages whose headers disagree → error.
   - Receipt before the effective time → error.
2. **Rows:** game date, game time (ET), matchup `AAA@HHH`, team, player `Last, First`, status, and reason (best effort; wrapped reason lines are flagged `reason_complete=False`).
   - Blank date, time, matchup or team cells carry forward from the previous row.
3. **Statuses:** OUT, DOUBTFUL, QUESTIONABLE, PROBABLE, AVAILABLE, and team-level NOT_YET_SUBMITTED. Anything else → error.
   - Every record has `participation="UNKNOWN"`, because listed AVAILABLE ≠ played.
4. **Team ID mapping is fail-closed.** Each team name must be one of the 30 fixed franchise names, and its tricode must equal one side of the row's matchup. Otherwise → error.
5. **Player ID mapping is fail-closed.** Mapping uses a caller-supplied as-of directory {(team tricode, normalized "Last, First") → player id}.
   - No match or more than one match → `player_id=None`, `mapping="UNMAPPED"`, availability UNKNOWN. Never guessed and never dropped.
6. **Unparseable lines** (containing a status word but no player/team context) → error. The whole report fails closed.

## Acceptance tests (on real PDFs saved as fixtures, with their extracted text)
- Header time differs from the filename slot. Effective time and receipt time are separate. DST is handled: a March report is in EDT.
- Fixture row counts and selected rows match hand-checked values.
- Fail-closed cases: unknown team, team not in matchup, unknown status, mismatched page header, unmapped and ambiguous players.
- The PDF sha256 is checked against the fixture. Re-extraction runs only if poppler is present (skipped otherwise).
