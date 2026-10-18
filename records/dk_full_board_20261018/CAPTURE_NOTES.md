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

## Late window — still outstanding (resumed capture in progress)
- ARI@LAR remaining sections: alternate spread/total ladders, standard pass/receive/rush O/U props, receptions and receiving/rushing yards props, team totals, halves (1H/2H), defensive and special teams markets.
- LAC@KC, BUF@LV, DAL@GB: everything beyond the main game lines — alternates, player props, team props/totals, halves, defensive and special teams sections.

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
