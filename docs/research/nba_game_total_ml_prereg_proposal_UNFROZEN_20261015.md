# NBA game total + moneyline backtest vs public baselines — PREREG PROPOSAL (UNFROZEN)

Status: **PROPOSAL_UNFROZEN — NOT A PREREGISTRATION.** Nothing in this document is
frozen, authorized or scored. It becomes a preregistration only when the owner
approves it and a frozen JSON copy (status `FROZEN_BEFORE_IMPLEMENTATION`) is
committed **before** any harness code touches the holdout window. Research only:
no model_p, no truth gate, no promotion, no staking, no activation, no market
admission. Author: Grok lane, 2026-10-15. Base: main `f113a3e8`.

## 1. Free data actually available (inventory, 2026-10-15)

| Source | Where | Coverage | Contents | Prior use (burn status) |
|---|---|---|---|---|
| ESPN summary cache | box `/workspace/nba_cache`, `nba_cache_q` | 2024-25 reg. season, 1,234 games (2024-10-22 → 2025-04-13) | final score, quarter linescore, team box | **Partly burned**: Oct 11 harness (`docs/NBA_HARNESS_VALIDATION_2026-10-11.md`) scored 310 games (every 4th day) of 2024-25 |
| ESPN summary cache | box `/workspace/nba_cache_q_2025_26` | 2025-26 reg. season, 1,235 games (2025-10-21 → 2026-04-13), retrieved 2026-10-13 | same as above | No recorded scoring run found in repo docs; **owner must confirm it is unseen** (box-only data, fetched by `fetch_nba_q_2025_26.py`) |
| ESPN player cache | box `/workspace/nba_cache_players` | 2024-25 | player box rows | not needed for this proposal |
| SBR public archive (`flancast90/sportsbookreview-scraper`) | **not on box**; cloned on demand by `scripts/backtest_nba_ratings_vs_lines.py` (free, public GitHub) | 2011-12 → 2021-22 | scores, open/close spread & total, closing ML | **Burned**: v1 (2026-10-03) and v2-rest (2026-10-04) fit 2012-14 and scored 2015-21 |
| Kaggle NBA odds | `scripts/archive_kaggle_nba_odds.py` (Actions-side, secret-gated) | unknown | odds | **Not on box, not on `data` branch.** Requires the Kaggle secret; not run here |
| `data` branch | origin/data | — | contains no NBA files | — |

No free source of **2022-23 or later** historical NBA closing lines exists in the repo
or on the box. Consequently a **market baseline cannot be evaluated retrospectively**
on any unburned season with current assets.

## 2. Question

Does a pregame team-strength model (existing `sportsedge.sports.nba.ratings_model`
/ `nba_game_market_pricing` path, frozen as of a named commit) beat **public,
non-market baselines** on (a) moneyline outcome probability and (b) game total
points, chronologically, on a season it has never been scored on?

This is a skill test, **not** an edge test. Passing cannot create betting authority.

## 3. Proposed windows

- Fit/tuning: 2024-25 regular season only (all 1,234 cached games). The 310 games
  already scored on Oct 11 are in-sample here, which is allowed for fitting.
- Holdout: 2025-26 regular season (cached, 1,235 games), **only if the owner
  confirms no prior scoring**; otherwise the holdout becomes forward-only (§7).
- Walk-forward inside the holdout: predictions for game *g* use only games with
  tipoff strictly before *g*'s tipoff − 60 min; ratings update after each game day.
- Exclusions: preseason, play-in, playoffs, NBA Cup final (non-standard rest),
  games with missing/ambiguous final score (counted and reported, never dropped silently).

## 4. Candidate (to be pinned at freeze)

- Commit SHA of the candidate code, the exact function entry points, and all
  hyperparameters fixed in the frozen JSON. No tuning after freeze.
- Outputs per game: P(home win) and a predictive distribution for total points
  (mean + scale; normal unless frozen otherwise).

## 5. Baselines (all public, no market prices)

Moneyline:
1. **B0 constant**: home-win rate from the fit window.
2. **B1 Elo**: standard Elo (K=20, home +100, carry 75% of rating between seasons, regress 25% to the mean) fit on 2024-25 only, parameters frozen in advance.
3. **B2 point-differential SRS**: rolling net rating → logistic, fit window only.

Total:
1. **T0**: fit-window league mean total, fit-window SD.
2. **T1**: rolling team points-for/against average (last 10, shrunk to league) with fit-window SD.

## 6. Metrics and decision rule (proposed; frozen only on owner approval)

- ML: log loss (primary), Brier, reliability (10 bins), with paired
  bootstrap 95% CI by game day (2,000 resamples, fixed seed in frozen JSON).
- Total: CRPS (primary), MAE, PIT-histogram coverage of the 50%/80% intervals.
- **PASS (skill only)** requires, on the holdout:
  - candidate log loss < every ML baseline with the paired 95% CI of the
    difference entirely below 0; and
  - candidate CRPS < every total baseline with the 95% CI entirely below 0; and
  - 80% interval empirical coverage within [0.75, 0.85].
- Any other result = FAIL, recorded as binding negative evidence. One attempt;
  no retuning on the same holdout.
- Multiple-comparison note: 2 primary tests, Bonferroni α = 0.025 each.

## 7. Market leg (not retrospectively possible)

The verification bar also requires beating the market. With no free post-2021
closing lines, the market leg can only be **forward**: from 2026-27 tip-off
(~2026-10-20), capture DK two-sided ML and total quotes pregame (existing
capture paths; capture/admission stay OFF until the owner enables them),
then compare log loss vs de-vigged close. Minimum forward sample and its
gate must be frozen in a separate prereg before the first forward game.

## 8. What needs owner authorization

1. Approve/modify this proposal and freeze it as JSON before any holdout code runs.
2. Confirm 2025-26 cache has never been scored (else holdout = forward only).
3. Decide whether the SBR archive may be cloned for an **in-sample** sanity check
   (it is burned; it cannot be used as evidence).
4. Separately authorize any forward capture for the market leg.

## 9. Explicit non-claims

No result exists. No game has been scored under this proposal. No probability
here is a price. NBA remains RESEARCH_ONLY / NO_VALIDATION for every market.
