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

- **College football:** every game in the F-6 discovered slate (registry ∪
  DraftKings league-page discovery) for the next 36 hours, entry capture
  and close capture, pre-start only:
  - main game lines: **moneyline, spread, total** — both sides of every
    two-sided market, exact DraftKings prices as displayed, no rounding,
    no −110 filler prices.
  - A market with a missing or suspended side is **left off entirely** and
    recorded missing with a named reason (Rule CFB-4). Never post a market
    one-sided.
  - Moneyline is captured alongside spread and total even though the
    CFB_GAME_EPA_JOINT_V1 validation covers spread and total only: the
    forward moneyline config and issue #2961's ordering require the same
    paired captures.
  - **Standing exclusions, enforced upstream:** Tennessee Volunteers games,
    Hawai'i @ Northern Illinois, and any Illinois college team are never
    captured and never issued. (Illinois professional teams are unaffected.)
    A game not present in the F-6 discovered slate does not get written from
    schedule data alone: no DK event id, no capture.

## Timing
- **Entry capture:** before kickoff. Recorded with its own timestamp.
- **Close capture:** the last capture before kickoff and no more than 60 minutes before kickoff.
  - Thursday's close window is 6:15–7:15 PM CT.
  - A capture older than 60 minutes before kickoff is not a close. The row is CLV_MISSING with reason CLOSE_STALE.
  - A close taken at or after kickoff is CLOSE_NOT_PREKICKOFF.

### Timing (CFB)

Two writes per game, maximum. No hourly refreshes, no first-sight creates,
no line-move-triggered edits.

- **Entry capture (T-1H mark):** the first check run that lands **90 to 60
  minutes before the game's start** posts the entry write. If the game's
  issue does not exist yet, it is created at this mark. A game first seen
  inside the window but after its mark gets its first write at the FINAL
  mark.
- **Close capture (FINAL mark):** the first check run that lands **within
  20 minutes before start** (target ~10 minutes before) posts the close
  write. **The FINAL write is the close** for every downstream test.
- **P-5 pre-dispatch:** each mark's capture pull is dispatched **20 minutes
  before its window opens** — T-1H at start−110m, FINAL at start−40m. The
  finished read is held and posted only once the window is open, and only
  if the read's age at post time is **≤ 15 minutes**; an older held read is
  discarded and a fresh capture is dispatched at window open.
- Per the spec's Timing rules: a capture more than 60 minutes before
  kickoff is not a close — the row is CLV_MISSING with reason
  **CLOSE_STALE**; a capture at or after kickoff is **CLOSE_NOT_PREKICKOFF**.
- **Stop editing at kickoff.** The last pre-start edit is the closing line.
  Never edit after start, never backdate.

## Row fields (every row, no exceptions)
- sport, league, event (teams and start time in CT)
- market, player (full name or nflverse player_id), line, side, price (American odds)
- book: DraftKings
- captured_at: ISO timestamp, to the minute, with timezone
- capture_type: ENTRY or CLOSE
- source: the DraftKings page or app view the price was read from
- entered_by: Muse

### Row fields (CFB — every row, no exceptions)

The spec's row-field list, carried in the per-game issue grammar and the
registry: sport, league, event (teams and start time in CT), market, line,
side, price (American), book (DraftKings), captured_at (ISO timestamp with
timezone, set at the moment the board is read), capture_type (ENTRY or
CLOSE), source (the rendered DraftKings page/view read — signed out,
rendered pages only, never the DK API), entered_by.

## Rules
1. No fabricated quotes. No prices reconstructed from memory or from later screenshots.
2. No retroactive entry prices.
3. No substitution of a partial board for a claimed full board. If a section could not be read, mark it missing and record which section.
4. Missing rows stay missing. Missing closes are CLV_MISSING with one named reason.
5. Two-sided markets record both sides. One-sided markets (anytime TD) record the Yes side only.
6. Screenshots are evidence attached to a row, never a substitute for a row.

### Rules (CFB additions to the spec's Rules)

- **CFB-1.** No fabricated quotes. No prices reconstructed from memory or
  from later screenshots. (Spec Rule 1, restated for CFB without change.)
- **CFB-2.** No retroactive closes. A missed mark is recorded missed; it
  is never backfilled. (Spec Rules 2 and 4.)
- **CFB-3.** No substitution of a partial board for a claimed full board.
  A capture that posts only main lines is DEPTH_INCOMPLETE and is named as
  such in the status line. (Spec Rule 3.)
- **CFB-4.** Missing closes stay missing with **exactly one named reason**:
  `NO_CLOSE_ROW`, `CLOSE_STALE`, `CLOSE_NOT_PREKICKOFF`, or
  `CLOSE_SINGLE_SIDED`. These are the reason codes the
  CFB_GAME_EPA_JOINT_V1 preregistration (§2.2(b)) reads; no other code may
  be attached to a CFB close.
- **CFB-5.** A game that has already started is never created or edited.
  Pregame only.
- **CFB-6.** Each due game's capture is dispatched as its **own task**,
  all due games in parallel; each game is posted immediately when its own
  detailed read returns, never held for another game's capture.

## Records
- Commit each capture to a records branch as it is taken, so the timestamp in the file is the time of capture.
- Thursday's records file is the proof for the anytime-TD and NFL-props forward tests.

### Issue format and registry (CFB)

- One **[CFB LINES] issue per game** (title: `[CFB LINES] Away @ Home`,
  DK's displayed team names). Adopt an existing matching issue; never open
  a duplicate.
- **Body line 1** is only `Away @ Home`. **Line 2** is a plain line:
  `Captured: <ISO 8601 timestamp with the Central offset in effect>`, set
  to the moment the board is **read**, never the time of posting. **Line
  3** is a comment tag holding the DK event id and all metadata and
  non-grammar material. Then one market per line in the parser grammar —
  away side first (line, away price, home price), exact prices, e.g.:
  - `Spread +6.5 -112 -108`
  - `Total 57.5 -110 -110`
  - `ML +190 -230`
- Bodies are built **only** from the capture harness's detailed per-game
  board read — matchup, DK event id, and every price cross-checked against
  that read before posting. A capture task's summary or narrative is never
  a data source.
- **Registry:** `lane_intakes/registry.json` maps DK event_id →
  {sport, issue_number, away, home, commence_ct, last_body, last_posted_ct,
  final_posted, status}. Read at the start of every run; updated after
  every create/edit. The registry fields drive the two marks; the five
  delivery timestamps (below) are recorded in the game's registry note.

### Delivery receipts (CFB) — five stages, every write

For every due write, record five authentic timestamps (§6B) in the run log
and in the game's registry note:

1. **Dispatch** time of that game's capture task (for a P-5 hold: the
   pre-dispatch time).
2. **Source-capture** time — the DK server time on the read; this is the
   issue's Captured line.
3. **Ingestion** time — body staged from the detailed read and
   cross-checked.
4. **Durable-write** time — the GitHub create/edit completion.
5. **Card-delivery** time, when a priced card consumes the write.

A write counts as **delivered** only when stage 4 completes **before the
game's start**. Every late or failed attempt is recorded permanently
(record-only file plus the #2447 status line) — never deleted, never
overwritten.

### Proof of discipline (CFB)

This section is in force for validation purposes only after the above is
**demonstrated over one full Saturday slate with five-stage receipts** —
every due game in the slate carrying its two marks, its receipts, and its
named reasons for any miss. That proof is the preregistration's §5.2
dependency and closes the Kent State P0 failure mode (an issue created
after kickoff, its T-1H mark missing, no within-window durable delivery
proven). The proof is delivery discipline and a data-provenance condition
on the prereg freeze; it is not a gate on any VERIFIED label.

This spec governs capture only. It does not change any frozen preregistration.
