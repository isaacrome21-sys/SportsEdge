# Pregame record — Cleveland Guardians @ Tampa Bay Rays, ALCS
- Fixture: gamePk 849813, first pitch 2026-10-14T00:00:00Z (Oct 13, 7:00 PM CT), Tropicana Field
- Probables (StatsAPI, verified): Parker Messick (CLE) vs Freddy Peralta (TB)
- Series: Cleveland leads 1-0
- Quotes: DraftKings public board. Game markets + team totals + pitcher props read 2026-10-13T10:08:00Z; batter props read 2026-10-13T10:04:00Z. Cross-book: OddsPortal + Action Network consensus (context only).
- Pricing run: canonical composition (drift-compose ed8a9390b = main bafe5a222 + stack heads, the verified composition), Lane A independent, run start 2026-10-13T10:10:21Z; supplementary TT/F5 pass 10:13:44Z.
- Validation status: NO family validated. Everything below is RESEARCH ONLY. Engine statuses quoted verbatim; end states per owner contract.

## Model view (one correlated view — all game-market numbers derive from the same two means)
- Lane A heuristic means (family FREE_TEAM_SCORE_HEURISTIC_UNVALIDATED): CLE 4.73 runs, TB 3.40 runs; projected total 8.13; projected margin CLE +1.33.
- Prepricing factors USED: starting pitchers (declared heuristic — Messick ERA 2.56/186.3 IP/32 GS; Peralta ERA 4.42/169.0 IP/32 GS, StatsAPI), weather INDOOR_VERIFIED, rest 1.0d both. PENDING_VALIDATION (zero pricing impact): bullpen, park, umpire, travel, lineups. NOT_WIRED: pace, advanced metrics, situational, opponent-adjusted offense.
- Market disagrees sharply: DK no-vig CLE 43.7%. Model-market divergence ≈24pp on ML — treat as model-risk flag, not established edge. Same heuristic family under-projected the Oct 12 CLE/TB total (6.66 vs actual 11).

## Selections (DK price / model p / fair / EV per $ / end state)
### WATCH — unvalidated model EV opportunities (engine: RESEARCH_POSITIVE_EV_UNVALIDATED)
- CLE ML +119 — p 0.677, fair −210, EV +0.482, no-vig 0.437. Lane B anchored: unavailable (BLOCKED_UNPAIRED_ML).
- OVER 7 (+102) — win 0.566 / push 0.137 / loss 0.297, fair −190, EV +0.280. NOTE: DK hangs 7; bet365/BetMGM/Action hang 6.5 (O −120ish). Cross-book line discrepancy disclosed, not averaged.
### WATCH — price-capped / below threshold
- CLE +1.5 (−194) — p 0.843, EV +0.278, engine status PRICE_CAP (exceeds −165 straight-price cap). Not playable per cap rule.
- TB ML −143 — p 0.323, EV −0.451, BELOW_THRESHOLD.
- TB −1.5 (+159) — p 0.157, EV −0.593, BELOW_THRESHOLD.
- UNDER 7 (−122) — win 0.297 / push 0.137 / loss 0.566, EV −0.322, BELOW_THRESHOLD.
### WATCH — research candidates (engine: RESEARCH_CANDIDATE_NOT_VALIDATED)
- YRFI +110 — p 0.593, fair −145, EV +0.245. (NRFI −145: p 0.407, EV −0.312, WATCH_BELOW_EV_FLOOR.)
- Messick OUTS OVER 14.5 (−126) — p 0.808, EV +0.449.
- Peralta OUTS OVER 13.5 (−124) — p 0.808, EV +0.459.
- Messick HITS ALLOWED OVER 4.5 (+115) — p 0.654, EV +0.406.
- Peralta HITS ALLOWED OVER 3.5 (−104) — p 0.654, EV +0.283.
- CAVEAT: outs/hits-allowed probabilities are IDENTICAL for both pitchers (0.808 / 0.654 = 21/26, 17/26) — pooled empirical sample artifact; treat as one shared estimate, not pitcher-specific.
### WATCH — quote not current (quotes from the 10:04Z/10:08Z reads, stale at supplementary run 10:13:44Z; model numbers computed)
- CLE team total OVER 3.5 (+120) — p 0.695, EV +0.529 (same aggressive means; stale).
- CLE team total UNDER 3.5 (−154) — p 0.305, EV −0.497.
- TB team total OVER 3.5 (−110) — p 0.443, EV −0.155.
- TB team total UNDER 3.5 (−120) — p 0.557, EV +0.022.
- Batter props for 5 players (Victor Mesa Jr., Ryan Vilade, Taylor Walls, Petey Halpin, Nick Fortes) — hits/TB/RBI/runs priced by the engine but WATCH_QUOTE_NOT_CURRENT (10:04Z quotes). Full numbers in card_mlb_canonical.json.
### BLOCKED
- F5 ML / F5 RL — NO_QUOTE: F5_QUOTE_STALE (quote age 344s > 180s bound at supplementary pricing; with gamePk 849813 + DK event 34817298 bound). F5 deployment gate (eligible=false) not reached. F5 total not offered at DK.
- Pitcher STRIKEOUTS (Messick 4.5, Peralta 3.5) + PITCHER_EARNED_RUNS — NO_ENGINE: MARKET_NOT_SUPPORTED_BY_REAL_PITCHER_ENGINE in the canonical path.
- Batter props for 13 players (Diaz, Caminero, Kwan, Ramirez, DeLauter, Aranda, Williamson, DeLuca, Lowe, Adell, Bazzana, Rocchio, Bailey) — NO_MODEL_OR_MARKET: HISTORY_LEAK_OR_DUPLICATE_GAME (engine fail-closed on their StatsAPI gamelog integrity). HR rows: additionally EXACT_PAIRED_DK_QUOTE_REQUIRED (DK offers 1+ single prices only).

## Grading
Append-only below this line after the final. Gradable rows are the ones above with line + price + timestamp.
---
