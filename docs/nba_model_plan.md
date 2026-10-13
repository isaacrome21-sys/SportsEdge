# NBA model foundation plan (research only)

Owner lane: Grok (MLB/NBA/CBB modeling). Base: main `ac598d708`.
Status: DESIGN ONLY. No pricing, eligibility, promotion, staking or workflow changes.
Shared pricing/catalog/card/routing changes require ChatGPT integration review.

## 1. Inventory on main (verified by file read, not prose)
| Area | Existing code | State |
|---|---|---|
| Canonical free path | `artifacts/free_models.py` NBA branch (ratings + HFA + injury pts) | Live research path; recent form and `rest_adj` contribute exactly 0 (owner ruling Oct 13, #2120/#2139) |
| Game ML/spread/total | `sportsedge/sports/nba/nba_game_market_pricing.py`, `ratings_model.py` | Harness CONDITIONAL_PASS on ML (Brier .2364 vs .2473 naive, n=1306); **market baseline MISSING** (`docs/NBA_HARNESS_VALIDATION_2026-10-11.md`) |
| Pace/efficiency | `pace_efficiency.py`, `pace_fit.py`, `possession_history.py` | Components exist; not the canonical price path |
| Periods | `periods.py`, `period_history.py` | Components; capability registry says period paths required, never scale full-game |
| Players | `player_history.py`, `player_stats.py`, `nba_public_player_history.py`, `nba_gamelog_decode.py`, `rotation.py`, `availability.py` | Components; minutes/usage not jointly simulated |
| Joint sim | `simulation.py`, `integrated_engine.py`, `run_it.py` | Present; validation status not recorded |
| Capability registry | `market_capabilities.py` | ML/spread/total/team totals/1H/quarters/PTS/REB/AST/3PM/PRA/PR/PA/RA = REQUIRES_ENGINE; first basket, double/triple-double = NO_ENGINE |
| Calibration/eval | `calibration.py`, `evaluation.py`, `training.py`, `backtest/kaggle_nba_baseline.py` | Present |

## 2. DK market families observed
The #2136 event-specific offering ledger (`sportsedge/dk_event_availability.py`) covers `SPORTS = {MLB, NFL, CFB}` only.
**Every NBA DK family is UNKNOWN (not inspected)** until a captured DK NBA board/category probe is recorded
(`.github/workflows/dk-nba-nhl-category-probe.yml` exists; no reviewed capture in the ledger). No family may be called offered or priced from this doc.

## 3. Free data sources (no paid historical odds)
- ESPN public scoreboard/summary/boxscore (games, quarter linescores, player box, injuries) — already used (`espn_verified_source.py`).
- NBA game logs via public ESPN gamelog decoder; sportsdataverse public datasets (`sportsdataverse_training_source.py`).
- Kaggle public NBA odds archive (`scripts/archive_kaggle_nba_odds.py`) = only possible historical **market baseline**; license/provenance and closing-timestamp quality must be verified before use. If unusable, market leg stays MISSING and nothing promotes.
- No Odds API archival calls.

## 4. Team model: possession / pace / efficiency
- Per-team PIT ratings: offensive and defensive points per 100 possessions, pace (possessions/48), shrunk to league mean (empirical Bayes), fit only on games strictly before as-of.
- Game expectation: possessions = f(pace_home, pace_away, league); points_i = possessions * ORtg_i vs DRtg_j / 100; HFA static term.
- Injury/availability enters only through the player model's minutes redistribution (Section 5), not a separate points heuristic, once validated; until then the existing injury-points term stays as is.
- `rest_adj` / back-to-back / travel: **DISABLED (exactly zero)** pending incremental-value proof vs retained baseline AND market. Rest days remain in context as research values only.

## 5. Player model: minutes / rotation / injury
- Minutes distribution per player from PIT role (starter/bench), recent minutes, availability status (OUT/DOUBTFUL/QUESTIONABLE as of capture time only), and team minutes constraint (240 + OT) with redistribution.
- Per-minute rates (usage, FGA/3PA, FT, REB chances, AST) with shrinkage; player stats generated **on the same simulated possessions** as team score.
- Combos (PRA/PR/PA/RA) summed per path, never from independent marginals. Double/triple-double stay NO_ENGINE until joint threshold calibration validates.

## 6. Coherent joint score distribution
- One simulation (or analytic convolution) produces per-quarter team points; halves, full game, team totals, spread, ML and OT come from the same paths.
- Regulation ties -> OT period paths (5 min, reduced pace); ML settles incl. OT; quarter/half markets settle on period only (DK 2-way vs 3-way rules verified per market before wiring; tie/push handled explicitly).
- Integer push mass preserved for whole-number lines.
- No full-game scaling to periods (registry rule).

## 7. Validation plan
- Chronological walk-forward by date; features computed strictly from data available before tip (PIT injuries by capture timestamp only; no post-game corrections).
- Metrics: log loss, Brier, calibration bins, CRPS for margin/total; vs (a) naive baseline, (b) current ratings model, (c) **market no-vig close** where a verified historical close exists.
- Promotion bar unchanged and owner-controlled: beating naive is not sufficient; market leg must be checked. A failed family is marked NOT_WIRED_WITH_REASON.
- Sealed holdouts untouched; no attempt resets.
- Each family ends PLAY / WATCH / BLOCKED with machine-readable reason; default WATCH or BLOCKED.

## 8. Build order (dependency)
1. Possession/pace/efficiency ratings PIT fit + harness (game ML/spread/total).
2. Quarter-level joint score paths + OT; team totals, 1H, quarters from same paths.
3. Minutes/rotation model with availability; then PTS/REB/AST/3PM and same-path combos.
4. Market-baseline leg once a verified free historical close source is confirmed.

## Decisions / missing sources
- OWNER: accept Kaggle archive as market baseline or keep MISSING.
- DK NBA catalog capture needed (category probe output reviewed into #2136-style ledger).
- Reuse note: no Muse NBA probe artifacts were found under /workspace at time of writing; credit them here if handed off.
