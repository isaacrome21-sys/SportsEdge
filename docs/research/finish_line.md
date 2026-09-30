# Finish line

**One sentence:** every sport runs on its own model, prices every market you care
about from one simulation of each game, and returns a clean card to your phone
minutes after you send lines. Every number traces back to real data, and every
probability has been checked against real results.

Cards stay `NOT Truth Gate / NOT OFFICIAL`. Lines stay manual. Everything else
is automatic. Nothing moves context → model without a one-shot holdout.

## Finished day

1. Paste DK lines into a phone issue (any sport).
2. System pulls starters/goalie/QB, lineups, injuries, rest, weather, logs. Time-stamped.
3. One simulation per game; every market from those paths.
4. PRE-CONTEXT, then the card: paired, no-vig, 2% floor, same-game guard, `NO_MODEL` never faked.
5. After the game: auto-grade results and close.

## Four checks every sport must pass

1. Real inputs: offense vs opponent defense, plus who is actually playing.
2. Realistic outcomes: score spread matches reality (MLB runs, NFL 3/7, NHL OT).
3. One simulation: ML, spread, totals, team totals, periods, props — same games.
4. Proven: one unused window, only promote if it beats the current owner.

## Current vs finish (2026-09-29)

| Sport | Finish | Now |
|---|---|---|
| MLB | Full game, F5, NRFI/YRFI, TT, starter-aware, pitcher/batter props | Game markets live (V7 + dispersion). Starter v2 not promoted. Props on #1243. F5 still fail-closed. |
| NFL | ML, all spreads incl. 3/7, totals, TT, halves/quarters, usage props | Phone card live. **`.5` totals only.** Discrete v1 **failed** 2025 push gate. Props #1250 pre-lock. |
| CFB | Same markets, FCS/altitude/neutral handled | UNFROZEN. `[CFB LINES]` is `NO_MODEL` (#1251). New unused window required. |
| NHL | ML, PL, totals, periods, SOG/G/A on confirmed goalie | Rate v1 **passed** 2025–26. Card still `NO_MODEL` until promotion. Goal/point props unsupported. |
| NBA | ML, spread, totals, halves/quarters, PTS/REB/AST from minutes | Engine in-tree. `[NBA LINES]` is `NO_MODEL` (#1251). Freeze + holdout remain. |
