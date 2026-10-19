# DraftKings Capture Spec, V1

Status: owner rulings recorded Oct 18, 2026. Capture owner: Muse, pending Muse's confirmation of access and acceptance.

## Ownership
- Line-entry owner: Muse. Muse enters every capture by hand from DraftKings.
- No capture is attributed to any person or session until a committed records file exists.
- Proof standard: a committed records file on a records branch, with source, timestamp, event, market, line and price on every row.

## Scope
- **Thursday, Oct 22, 2026, New England at Chicago, 7:15 PM CT kickoff:** full available DraftKings board for that game, entry capture and close capture.
- **All other games:** the predeclared subset, entry and close:
  - the four scored NFL prop markets: passing yards, rushing yards, receiving yards, receptions
  - the anytime TD Yes board
  - main game lines: moneyline, spread, total
- **NBA:** game lines plus points, rebounds, assists and common combination props.
- **College basketball:** the complete available game-line board first (moneylines, spreads, totals, team totals), then available player props.

## Timing
- **Entry capture:** before kickoff. Recorded with its own timestamp.
- **Close capture:** the last capture before kickoff and no more than 60 minutes before kickoff.
  - Thursday's close window is 6:15–7:15 PM CT.
  - A capture older than 60 minutes before kickoff is not a close. The row is CLV_MISSING with reason CLOSE_STALE.
  - A close taken at or after kickoff is CLOSE_NOT_PREKICKOFF.

## Row fields (every row, no exceptions)
- sport, league, event (teams and start time in CT)
- market, player (full name or nflverse player_id), line, side, price (American odds)
- book: DraftKings
- captured_at: ISO timestamp, to the minute, with timezone
- capture_type: ENTRY or CLOSE
- source: the DraftKings page or app view the price was read from
- entered_by: Muse

## Rules
1. No fabricated quotes. No prices reconstructed from memory or from later screenshots.
2. No retroactive entry prices.
3. No substitution of a partial board for a claimed full board. If a section could not be read, mark it missing and record which section.
4. Missing rows stay missing. Missing closes are CLV_MISSING with one named reason.
5. Two-sided markets record both sides. One-sided markets (anytime TD) record the Yes side only.
6. Screenshots are evidence attached to a row, never a substitute for a row.

## Records
- Commit each capture to a records branch as it is taken, so the timestamp in the file is the time of capture.
- Thursday's records file is the proof for the anytime-TD and NFL-props forward tests.

This spec governs capture only. It does not change any frozen preregistration.
