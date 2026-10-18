# MLB F5 run share and team-total ladder: walk-forward (2024 + 2025)

Research only. Outputs are model probabilities only, kept separate from market data. The market baseline is **MISSING** (no paired, timestamped odds). F5 `eligible=false` and `config/deployments.json` are unchanged. No registry or catalog edits.

## Data
- Free MLB Stats API `schedule?sportId=1&gameType=R&hydrate=linescore`, one call per month, cached outside the repo (`/workspace/mlb_cache`).
- 4,857 final regular-season games (2,427 in 2024 and 2,430 in 2025). Records are deduped by gamePk. Games with fewer than 5 innings, or without a timezone-aware start time, are dropped.

## Point-in-time rule (review item 1)
- The cutoff for a slate is its earliest first pitch.
- A game trains only when it is **FINAL** and its final linescore was available by the cutoff: `final_at` if recorded, else start + **6h** conservative buffer (`is_trainable`).
- A game that started earlier but was not final at the cutoff is excluded. This includes a late game the previous night and an earlier doubleheader game. Tests cover both.

## Method (`sportsedge/mlb_f5_walkforward.py`, `scripts/run_mlb_f5_walkforward.py`)
- **F5 run share s:** sum of F5 runs over sum of regulation runs, over trainable 9+-inning games (at least 30).
- **Team mean:** full-game runs scored over the team's last 30 trainable games (at least 10), through the frozen `calibrated_full_game_means`.
- **Model:** each team's F5 runs ~ NB(r = full-game r, s·μ).
- **Naive baseline:** the trainable league frequency of team F5 runs > line.

## Results (team-games; lower is better)

| Line | n | Brier model | Brier naive | LL model | LL naive | mean p | hit rate |
|---|---|---|---|---|---|---|---|
| 0.5 | 9398 | 0.1727 | 0.1692 | 0.5341 | 0.5215 | 0.845 | 0.784 |
| 1.5 | 9398 | 0.2466 | 0.2440 | 0.6868 | 0.6810 | 0.627 | 0.578 |
| 2.5 | 9398 | 0.2413 | 0.2408 | 0.6757 | 0.6746 | 0.427 | 0.403 |

The model loses to naive in each season and at every line. Final s = 0.577.

**Finding:** the thinning-coherent F5 NB, which carries the full-game r = 3.13 into F5, puts too little mass at 0. It overstates OVER by about 6 points at 0.5 and about 5 at 1.5. **Do not promote.** Next: a pre-registered, PIT-fitted F5-specific dispersion or zero-inflation term, evaluated on a holdout split, never tuned on these numbers.

## Settlement: UNVERIFIED_DK_RULES (review item 2)
All settle helpers return `settlement_status = UNVERIFIED_DK_RULES`, `grade = None` and `authoritative = False`, with a structural outcome only. These items need a live DK rules page capture (`DK_RULES_REQUIRED`):
- F5 action rule for shortened or suspended games, or games ending before 5 full innings (including a home team leading after 4.5);
- whether listed-pitcher changes void F5 bets;
- the exact Either-Pitcher proposition (max of the two, either-over, or combined) and whole-line push;
- Either-Pitcher void or action when a listed pitcher does not start or leaves early;
- whether relief appearances count.

## F5 game-total offering (review item 3)
`f5_game_total_offering(reconciliation, event_id)` reads the per-event #2136 `DK_EVENT_COVERAGE_RECONCILIATION_V1` row:
- OFFERED_ON_THIS_EVENT or NOT_OFFERED_ON_THIS_EVENT only from matching-event evidence;
- otherwise UNKNOWN (uninspected, a different event, missing from the ledger, or NOT_VERIFIED).

It is never universal and produces no probability or price.
