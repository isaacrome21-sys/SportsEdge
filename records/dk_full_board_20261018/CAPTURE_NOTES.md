# DraftKings Full-Board Capture — Notes (Sun Oct 18, 2026)

## Source
- DraftKings Sportsbook, **signed-out board** (no account session), read in the browser.
- All times America/Chicago.

## Capture windows
- **10:33 AM CT** — earlier main-lines pass over the noon slate (comparison reads).
- **~10:46–10:47 AM CT** — main board for all 7 noon games (moneyline / spread / total).
- **~10:48 AM CT** — CHI@ATL event page: ML re-read, full alternate spread ladder, full alternate total ladder, TD scorers.
- **10:49–10:50 AM CT** — CHI@ATL passing markets.

## What is present (file: `nfl_noon_partial.json`)
- Main lines (ML / spread / total, both sides) for all 7 noon games: CHI@ATL, NYJ@NE, CAR@PHI, TEN@IND, BAL@CLE, PIT@TB, NO@NYG.
- Line moves / discrepancies recorded with their times, exactly as read:
  - CHI@ATL ML: CHI −120 / ATL +100 at 10:33 → CHI −118 / ATL −102 on the event page at 10:48 (moved during capture).
  - PIT@TB ML: PIT −130 / TB +110 at 10:33 → PIT −135 / TB +114 on the 10:46 board.
  - TEN@IND spread −6.5 prices flipped between reads: TEN +6.5 (−108) / IND −6.5 (−112) at 10:33 → TEN +6.5 (−112) / IND −6.5 (−108) at 10:46. The line itself (−6.5) did not move.
- CHI@ATL extended sections:
  - Alternate spread ladder — COMPLETE, 46 rungs (CHI −24.5 through CHI +24.5 in 1-point steps). Endpoints and 8 mid anchor rungs are transcribed in the JSON; the full rung-by-rung table exists in the capture report.
  - Alternate total ladder — COMPLETE, 46 rungs (29.5 through 76.5). Endpoints and 2 mid rungs transcribed in the JSON; full table in the capture report.
  - TD scorers — full board (27 entries incl. No TD Scorer), Anytime / First / 2+ prices.
  - Passing — pass yards, pass TDs, interceptions, pass attempts for Michael Penix Jr. and Caleb Williams.

## SGP availability
- **SGP (Same Game Parlay) is offered on all 7 noon games** — the SGP tag appears on every noon game card.
- CHI@ATL confirmed in detail: a Quick SGP button and market-group tabs are present on the event page.

## Still outstanding (resumed capture in progress)
- Full boards for games 2–7 (NYJ@NE, CAR@PHI, TEN@IND, BAL@CLE, PIT@TB, NO@NYG): alternate lines, player props (QB/RB/WR), team props, halves, defensive and special teams sections.
- CHI@ATL remaining sections: receiving props, rushing props, team totals, halves (1H/2H), defensive and special teams markets.

## Discipline note
This is a partial, pregame snapshot — not closing lines. Only values actually read are recorded; moved or double-read prices are kept with their timestamps rather than reconciled.

## Late window — partial (file: `nfl_late_partial.json`)
Captured later the same morning, DraftKings signed-out, America/Chicago:
- **~10:54 AM CT** — game lines (ML / spread / total, both sides) for all 4 late-window games from the league page: ARI@LAR (3:05 PM), LAC@KC (3:25 PM), BUF@LV (3:25 PM), DAL@GB (7:20 PM).
- **~10:55 AM CT** — ARI@LAR extended sections: TD scorers (full board, 32 entries incl. No TD Scorer) and pass-yards milestone ladders for Matthew Stafford (27 rungs) and Jacoby Brissett (28 rungs).
- Line move recorded with both reads: LAC@KC moved between the 10:33 AM read and the ~10:54 AM read — spread KC −7 (−115) / LAC +7 (−105) → KC −7.5 (−105) / LAC +7.5 (−115); ML LAC +310 / KC −395 → LAC +330 / KC −425; total 41.5 prices −110/−110 → −112 (over) / −108 (under). ARI@LAR, BUF@LV and DAL@GB game lines matched their 10:33 AM reads.

## Late window — COMPLETE with named gaps (file: `nfl_late_full.json`)
Afternoon refresh pass, DraftKings signed-out, America/Chicago, **Sun Oct 18, 3:00–3:19 PM CT**. All four games captured in full structured form (game → section), with the morning 10:54 AM league-page reads preserved alongside for the line-move record. The `nfl_late_partial.json` file remains the morning record (its ARI@LAR 10:55 AM pass-yards milestone set is SUPERSEDED by the refreshed ~3:00 PM set in the full file; its TD board was re-read in the afternoon with identical values).

- **ARI@LAR (3:05 PM kickoff) — capture window 3:00–3:05 PM CT; BOARD FINAL.** The game kicked off at 3:05 PM CT during its capture and was live (Q1, ARI 0 – LAR 3 seen ~3:15 PM) while the other games were read; it was not re-attempted. All ARI@LAR prices are the last pregame reads (game lines refreshed 3:01 PM). Captured: refreshed game lines, the full two-sided **Passing O/U set (this game's passing accordion DID expand** — pass yards / TDs / interceptions / attempts / completions / pass+rush yards / longest completion, both QBs), refreshed pass-yards milestone ladders (Stafford 28 rungs, Brissett 28), receiving (13 players) and rushing (6 players) milestone ladders, TD scorers (32, from the ~10:55 AM read), full alternate spread (45 rungs) and alternate total (47 rungs) ladders, team-totals ladders (ARI 21, LAR 21 rungs), 1st-half lines, sacks milestones (Aaron Donald kept as two timestamped reads — 1+ +216/+212, 2+ +1340/+1240 at 3:03/3:04 PM — price drifted in the minute before kickoff), FG-made milestones (at kickoff the FG Made section showed "NO AVAILABLE BETS"), SGP present.
- **LAC@KC (3:25 PM) — capture window 3:05–3:11 PM CT.** Captured: refreshed game lines (3:05–3:06 PM), TD scorers (31), pass-yards milestones (Mahomes 24, Herbert 21 rungs), receiving (14) and rushing (7) milestone ladders, full alternate spread (41) and alternate total (42) ladders, team totals (KC 21, LAC 20 rungs), 1st-half lines, sacks (7 players) and FG-made milestones, SGP present.
- **BUF@LV (3:25 PM) — capture window 3:11–3:13 PM CT.** Captured: refreshed game lines (3:11 PM), TD scorers (29), pass-yards milestones (Cousins 26, Allen 24), receiving (13) and rushing (6) milestone ladders, full alternate spread (44) and alternate total (47) ladders, team totals (21 each), 1st-half lines, sacks 1+ milestones (9 players), FG-made milestones, SGP present with 20 prebuilt cards.
- **DAL@GB (7:20 PM) — capture window 3:13–3:19 PM CT.** Captured: refreshed game lines (3:13 PM), TD scorers (30), pass-yards milestones (Prescott 26, Love 27), receiving (14) and rushing (6) milestone ladders, full alternate spread (46) and alternate total (47) ladders, team totals (21 each), 1st-half lines, sacks (8 players) and FG-made milestones, SGP present with 20 prebuilt cards and a 30% SGP profit-boost promo.

### The named gap — two-sided O/U accordion sections (site-wide)
Across all four event pages, the two-sided O/U accordion sections could not be expanded — expansions stalled ("unknown (deadline)") after one attempt plus one retry. They are recorded per game in `nfl_late_full.json` under `unreadable_sections` as explicit UNREADABLE entries (null, never filled):
- **ARI@LAR:** Rec Yards O/U, Receptions O/U, Longest Reception O/U + Longest Reception; Rush Yards O/U, Rush Attempts O/U, Rush + Rec Yards O/U, Longest Rush O/U + Longest Rush; defensive Tackles / Assists / Tackles+Assists / Interceptions / Sacks O/U / Tackles O/U / Assists O/U / Tackles+Assists O/U; Kicking Pts O/U, FG Made O/U. **(Passing O/U is NOT in this gap for ARI@LAR — it came through in full.)**
- **LAC@KC:** all two-sided O/U sections on the Passing/Receiving/Rushing tabs (19 named sections, incl. Pass Yards O/U, Rec Yards O/U, Receptions O/U, Rush Yards O/U, Longest Completion/Rush/Reception), the Receptions and Rush + Rec Yards milestone carousels, the two-sided defensive O/U sections (8 named), Kicking Pts O/U, FG Made O/U.
- **BUF@LV:** all two-sided O/U sections on the Passing/Receiving/Rushing tabs, the other two-sided defensive O/U sections, Kicking Pts O/U, FG Made O/U — plus PARTIALLY unreadable: Sacks 2+ prices (the carousel rendered 2+ rungs without prices; 1+ prices captured).
- **DAL@GB:** all two-sided O/U sections on the Passing/Receiving/Rushing tabs (19 named), the two-sided defensive O/U sections (9 named, incl. Sacks in Each Half), Kicking Pts O/U, FG Made O/U, PAT Made O/U. (The Special Teams tab also stalled on skeleton loaders on first load; one reload rendered the FG-made milestones.)
- 2nd-half sections are listed pregame (collapsed) on all four games; 2nd-half prices post at halftime and were not captured — same standing as the noon slate.

### Late line moves — morning reads → afternoon refresh
- **ARI@LAR:** final pregame read 3:01 PM — ML **ARI +550 / LAR −800 (unchanged)**; spread prices moved: ARI +12.5 −108 → **−105**, LAR −12.5 −112 → **−115**; total 51.5 prices flipped: Over −115 → **−105**, Under −105 → **−115**.
- **LAC@KC:** ML **LAC +330 → +350, KC −425 → −455**; spread prices: LAC +7.5 −115 → −112, KC −7.5 −105 → −108; total 41.5 unchanged (−112/−108).
- **BUF@LV:** ML **BUF −245 → −238, LV +200 → +195**; spread (−5.5/+5.5) and total (53.5) prices unchanged.
- **DAL@GB:** ML **DAL −105 → −108, GB −115 → −112**; spread (+1.5/−1.5) and total (53.5) prices unchanged.

## MLB — complete (file: `mlb_alcs_g5_full.json`)
- **One game only on today's DK MLB board:** ALCS Game 5 — Tampa Bay Rays @ Cleveland Guardians, Progressive Field, first pitch 4:10 PM CT per the DK page header. Starters: Drew Rasmussen (TB) vs Parker Messick (CLE).
- **Capture window ~10:54–11:06 AM CT**, DraftKings signed-out board.
- **Drift note:** values in the file are last-observed prices — small drift occurred ~10:55→11:04 AM CT on some alt-total rungs and prop prices during the read; the final values are the ones recorded.
- Sections captured in full: game lines (ML / run line / total 6.5), alternate totals (16 rungs) and alternate run lines (16 rungs), F5 / 1st inning / 1st 3 innings / 1st 7 innings boards (ML, run lines, totals, team totals, both-teams-to-score, margins, period HR), per-inning run totals and winners (2nd–9th), first-of-game markets, team totals with alternate ladders, pitcher props (K milestones and O/U, outs, hits/ER/walks allowed ladders), the full batter-prop suite (HRs, hits, total bases, RBIs, stolen bases, XBH, H+R+RBI, H+R+SB, H+W+SB, runs, walks), 1st-plate-appearance exact results and on-base prices, either/combined batter HR pairs, game props, correct score (45 scores), and SGP (available — Quick SGP plus 8 prebuilt cards).
- Named but not enumerated (rendered on the page; prices not transcribed): Pitcher tab — Hits+Walks+ER, Hits Allowed O/U, ER Allowed O/U, Walks Allowed O/U, Hits+Walks+ER O/U, To Record a Win (main formats captured above); Batter tab — Singles, Doubles, Triples, Batter Ks, Runs+RBIs, Hits+SB, O/U-format sections (Hits, TB, RBIs, HRR, Runs, Singles, Doubles, Walks, SB), HRs 1st 5 Innings; Innings tab — per-inning Run Line + per-inning Props; Either/Combined tab — either/combined versions of Hits, TB, SB, Singles, Doubles, Triples, RBIs, Pitcher Ks, Hits Allowed, ER, Walks (HR versions transcribed); Plate Appearance tab — pitcher-batter matchup lines beyond 1st-PA.

## Noon NFL — complete

- **7/7 noon games captured in full:** CHI@ATL, NYJ@NE, CAR@PHI, TEN@IND, BAL@CLE, PIT@TB, NO@NYG — structured file `nfl_noon_full.json` (game → section). CHI@ATL's alternate ladders, TD scorers, and passing yards/TDs/INTs/attempts were banked earlier in `nfl_noon_partial.json` and are referenced, not repeated, in the full file.
- **Pregame window ~10:55–11:30 AM CT, Sun Oct 18 2026** (DraftKings signed-out board); server clock ~11:30 CT at final capture. Main lines re-verified 11:18–19 CT; team totals + 1st-half lines captured 11:15–11:17 CT; player props 10:55–11:14 CT by game; defense/special-teams/game-specials 11:19–11:30 CT.
- **2nd-half lines NOT offered pregame on any game.**
- Sections named but not expanded in this capture: Defensive Tackles/Assists O/U detail (beyond the transcribed boards), Special Teams kicking-pts / PAT / punt / FG-yards / FG-total O/U detail, Game Specials Half Specials.
- **Line moves vs the 10:33 CT read:** PIT spread −1.5 → −2.5 (−108), PIT ML −130 → −142; TB +1.5 → +2.5 (−112), TB ML +110 → +120; NYJ +7.5 spread price −112 → −115; NE −7.5 spread price −108 → −105; CHI@ATL ML −120/+100 → −118/−102; TEN@IND spread-price flip on the −6.5/+6.5 (10:33: TEN −108 / IND −112 → final: TEN −115 / IND −105).
