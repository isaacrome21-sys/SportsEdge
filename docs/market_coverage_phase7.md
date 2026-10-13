# Phase 7 — Market Coverage: classification & harness verdicts (2026-10-11)

Branch: `feat/market-coverage-20261011` (from `origin/main` 5e161b9).
Research only. No Model_P, no Truth Gate, no staking authority.

## Method

For every DK market in scope: (1) checked current code, (2) assessed whether a
verifiable free-data path exists, (3) built where verifiable, (4) classified
NOT_WIRED / BLOCKED with explicit reasons otherwise. Everything built was run
through the backtest harness (`~/workspace/sportsedge-backtest`, chronological
walk-forward, no lookahead) as candidate vs naive baseline (train base rates).
No market baseline exists anywhere (no Odds API on the pricing side), so the
best achievable verdict is CONDITIONAL_PASS. Failing markets are recognized
for routing but fail closed (`COVERAGE_MARKET_FAILED_VALIDATION_NOT_WIRED`).

Validation data (all free, cached): 2024 NFL season (272 games, ESPN
scoreboard with quarter linescores), 2024 CFB season (917 games), 2024 MLB
Apr–Sep (2374 games, StatsAPI schedule with inning linescores). Candidate
means are train-restricted (prior-5 margin proxy, same formula family as
`free_models`, no lookahead). Limitation: validation means omit
injury/form/weather/pitcher context the production pricer carries; the fails
are large enough that context is unlikely to reverse them, but a full-context
re-run is a valid follow-up.

## Classification table

Status values: SUPPORTED | IN_BUILD (shipped, CONDITIONAL_PASS) |
NOT_WIRED_WITH_REASON | BLOCKED_WITH_REASON | OWNED_BY_OTHER_WORK |
OUT_OF_SCOPE (other phase).

### MLB

| Market | Status | Reason / verdict |
|---|---|---|
| Moneyline (2-way) | SUPPORTED | pre-existing |
| 3-way moneyline (9-inning result) | NOT_WIRED_WITH_REASON | Built (`ML_3WAY`, Poisson 9-inning), then FAILED harness vs naive: Brier 0.1930 vs 0.1918, log-loss 0.5628 vs 0.5582, n=254301. Likely causes: margin-proxy means carry no 9-inning-outcome signal beyond base rates; home bottom-9th truncation not modeled. Gated: `COVERAGE_MARKET_FAILED_VALIDATION_NOT_WIRED`. |
| Run line -1.5/+1.5 | SUPPORTED | pre-existing SPREAD routing |
| Run line alternates | SUPPORTED | pre-existing SPREAD routing (any line); routing regression-tested |
| Game total | SUPPORTED | pre-existing |
| Game total alternates | SUPPORTED | pre-existing TOTAL routing; harness check on the underlying Poisson total: FAIL vs naive (Brier 0.2388 vs 0.2341, n=847670) — the margin-proxy mean construction carries no total signal (margin ≠ total). Routing unchanged (pre-existing behavior); flagged for coordinator: the base total engine needs validation/repair (out of Phase 7 scope). |
| Team total (full-game) | OWNED_BY_OTHER_WORK | `TEAM_TOTAL` built by team-half branch (`feat/team-half-pricing-20261011`, pending Isaac's submit); not duplicated |
| F5 moneyline | NOT_WIRED_WITH_REASON | Wired the empirical stack into phone RUN IT, then FAILED harness vs naive: Brier 0.2179 vs 0.2132, log-loss 0.7038 vs 0.6940, n=2898. The 10–30-game empirical F5 histories do not beat train base rates out-of-sample. Gated: `F5_MARKET_FAILED_VALIDATION_NOT_WIRED`. |
| F5 run line | NOT_WIRED_WITH_REASON | same — gated |
| F5 totals | NOT_WIRED_WITH_REASON | same — gated |
| F5 team totals | NOT_WIRED_WITH_REASON | same — gated |
| First to score (team) | BLOCKED_WITH_REASON | `NO_VERIFIED_SCORING_TIMING_MODEL` — team-level score means do not determine first-scorer timing; needs play-by-play timing distributions (unvalidated) |
| Race to X runs | BLOCKED_WITH_REASON | `NO_VERIFIED_SCORING_TIMING_MODEL` — needs P(team reaches X first) from scoring-timing distributions |
| Exact score | NOT_WIRED_WITH_REASON | `NO_JOINT_SCORE_DISTRIBUTION_WITH_CORRELATION` — independence-Poisson product would systematically misprice (home bottom-9th truncation, extra innings, game-state correlation); not built, not validated |
| Pitcher props (K/outs/hits/BB/ER) | SUPPORTED | pre-existing routing verified by test |
| Batter props (hits/TB/RBI/runs/HR/SB) | SUPPORTED | pre-existing routing verified by test |

### NFL / CFB

| Market | Status | Reason / verdict |
|---|---|---|
| Moneyline / spread / total | SUPPORTED | pre-existing |
| Alternate spreads | SUPPORTED | pre-existing line-param routing; harness: CONDITIONAL_PASS vs naive, both sports (NFL: Brier 0.1756 vs 0.1853 n=2048; CFB: 0.1742 vs 0.1853 n=5076) |
| Alternate totals | SUPPORTED | pre-existing line-param routing; harness is MIXED: NFL totals marginal CONDITIONAL_PASS (0.2220 vs 0.2256 n=1280), CFB totals FAIL (0.2257 vs 0.2233 n=3384), MLB totals FAIL (0.2388 vs 0.2341 n=847670). 4 of 5 total families fail — the margin-proxy mean construction carries little total signal (margin ≠ total). Routing unchanged (pre-existing behavior); flagged for coordinator: the base total engine needs validation/repair (out of Phase 7 scope). |
| Quarter spread 1Q–4Q | IN_BUILD | `SPREAD_1Q..4Q`, declared 0.25 fraction + halved sds; harness: CONDITIONAL_PASS vs naive (NFL and CFB) |
| Quarter moneyline 1Q–4Q | IN_BUILD | `ML_1Q..4Q`, discretized tie mass; harness: CONDITIONAL_PASS vs naive (NFL and CFB) |
| Quarter total 1Q–4Q | NOT_WIRED_WITH_REASON | Built, then FAILED harness vs naive (NFL: Brier 0.2409 vs 0.2239 n=3072; CFB: 0.2415 vs 0.2336 n=10152). The margin-proxy means carry side signal but no total signal. Gated. |
| Quarter team total 1Q–4Q | NOT_WIRED_WITH_REASON | Built, then FAILED harness vs naive (NFL: 0.2355 vs 0.2216 n=6144; CFB: 0.1886 vs 0.1749 n=20304). Gated. |
| Winning margin bands | IN_BUILD | `MARGIN_BAND` (1-6/7-12/13-18/19-24/25+, home/away), normal margin discretized ±0.5, declared tie mass; harness: CONDITIONAL_PASS vs naive (NFL and CFB) |
| Team total (full-game) | OWNED_BY_OTHER_WORK | team-half branch; not duplicated |
| Anytime TD | BLOCKED_WITH_REASON | `NO_VERIFIED_RUSH_RECEIVING_TD_HISTORY` — ESPN gamelog decoder carries only `passing_tds`; rushing/receiving TDs deliberately excluded as ambiguous. Unblock: verified per-game rush/rec TD indicators (decoder extension with unambiguous stat names, or nflverse in Phase 3) |
| First TD (player) | BLOCKED_WITH_REASON | `NO_VERIFIED_FIRST_SCORING_ATTRIBUTION` — needs per-player first-TD shares from play-by-play (not in pipeline) plus the TD-history gap above |
| First to score (team) | BLOCKED_WITH_REASON | `NO_VERIFIED_SCORING_TIMING_MODEL` |
| Race to X (team) | BLOCKED_WITH_REASON | `NO_VERIFIED_SCORING_TIMING_MODEL` |
| Exact score | NOT_WIRED_WITH_REASON | `NO_JOINT_SCORE_DISTRIBUTION_WITH_CORRELATION` — football normal marginals don't form a joint without correlation structure |
| 3-way moneyline | NOT_WIRED_WITH_REASON | `NOT_OFFERED_BY_DK` — not a DK-offered market for football; 2-way ML stands |
| Player props (yards/TDs/receptions) | SUPPORTED | routing verified; pricing is the pre-existing ESPN gamelog empirical path (activation pending gamelog-shape-fix merge — source fails closed until then) |

### Out of scope for Phase 7

| Market | Status |
|---|---|
| NBA everything | OUT_OF_SCOPE → Phase 5 |
| Live/in-game | OUT_OF_SCOPE → Phase 6 |
| MLB innings / FIRST_INNING_* / TEAM_HITS | OUT_OF_SCOPE → Phase 1 |
| Free factors (park/rest/weather/key numbers/umpires) | OUT_OF_SCOPE → Phase 2 |
| Tracking data (Statcast/Next Gen) | OUT_OF_SCOPE → Phase 3 |
| Futures, SGPs/teasers | NOT_WIRED (matrix: long-horizon / correlation modeling out of scope) |

## Harness verdicts (candidate vs naive; market baseline MISSING everywhere)

| Family | Verdict | n | Brier (cand/naive) | Log-loss (cand/naive) |
|---|---|---|---|---|
| nfl_q_spreads | CONDITIONAL_PASS | 4096 | 0.2380/0.2407 | 0.6689/0.6746 |
| nfl_q_ml | CONDITIONAL_PASS | 1024 | 0.2007/0.2046 | 0.6872/0.6951 |
| nfl_q_totals | FAIL | 3072 | 0.2409/0.2239 | 0.6751/0.6391 |
| nfl_q_team_totals | FAIL | 6144 | 0.2355/0.2216 | 0.6636/0.6317 |
| nfl_margin_bands | CONDITIONAL_PASS | 1280 | 0.0864/0.0876 | 0.3049/0.3133 |
| nfl_alternates | CONDITIONAL_PASS | 3328 | 0.1935/0.2008 | 0.5702/0.5885 |
| nfl_alt_spreads | CONDITIONAL_PASS | 2048 | 0.1756/0.1853 | 0.5297/0.5544 |
| nfl_alt_totals | CONDITIONAL_PASS (marginal) | 1280 | 0.2220/0.2256 | 0.6351/0.6430 |
| cfb_q_spreads | CONDITIONAL_PASS | 20304 | 0.2130/0.2151 | 0.6156/0.6214 |
| cfb_q_ml | CONDITIONAL_PASS | 3384 | 0.1997/0.2013 | 0.6784/0.6828 |
| cfb_q_totals | FAIL | 10152 | 0.2415/0.2336 | 0.6762/0.6594 |
| cfb_q_team_totals | FAIL | 20304 | 0.1886/0.1749 | 0.5623/0.5312 |
| cfb_margin_bands | CONDITIONAL_PASS | 4230 | 0.0878/0.0891 | 0.3126/0.3195 |
| cfb_alternates | CONDITIONAL_PASS | 8460 | 0.1948/0.2005 | 0.5718/0.5861 |
| cfb_alt_spreads | CONDITIONAL_PASS | 5076 | 0.1742/0.1853 | 0.5238/0.5510 |
| cfb_alt_totals | FAIL (marginal) | 3384 | 0.2257/0.2233 | 0.6438/0.6387 |
| mlb_3way | FAIL | 4353 | 0.1944/0.1931 | 0.5661/0.5616 |
| mlb_alt_totals | FAIL | 14510 | 0.2400/0.2345 | 0.6751/0.6617 |
| mlb_f5_moneyline | FAIL | 2898 | 0.2179/0.2132 | 0.7038/0.6940 |

CONDITIONAL_PASS = beats naive on Brier and log-loss; market-baseline leg
unchecked (no archived prices). Per the harness README this is not a full
pass — do not promote on this verdict alone; all shipped markets remain
research-only and unvalidated vs closes.

## What was built

- `sportsedge/market_coverage.py` — coverage pricers (quarter spread/ML,
  margin bands; quarter totals/team totals and 3-way implemented but
  validation-gated), full `free_models.calculate` mean construction replicated
  exactly (injuries included — never the participation-blind simplified
  variant), degenerate-probability fail-closed on reported values, explicit
  reason codes.
- `sportsedge/mlb_phone_f5_pricing.py` — phone intake wiring the existing
  empirical F5 stack (strictly-prior linescore F5 histories, 10-game minimum,
  M30 league prior) into RUN IT with the same EV/status shape as game markets.
  **Validation-gated**: the wired F5 moneyline failed the harness vs naive
  (Brier 0.2179/0.2132, n=2898), so all F5 markets fail closed
  (`F5_MARKET_FAILED_VALIDATION_NOT_WIRED`) until a verifying model exists.
- `artifacts/run_it_full.py` — routing for coverage + F5 markets, alias
  normalization, count checks, receipts, factor-audit as game-level.
- `scripts/validate_market_coverage.py` — reproducible harness validation
  (loads the harness from `~/workspace/sportsedge-backtest` without copying).
- `tests/test_market_coverage.py` (22) + `tests/test_market_coverage_adversarial.py`
  (45): pricer math, fail-closed paths, adversarial attacks (extreme
  lines/odds, decimal-odds confusion, null fields, contradictory/duplicate
  rows, degenerate p, ambiguous team identity, full stub-getter F5
  integration).

## Adversarial testing ("try to break it")

Attacks run and fixed, each with a regression test:
- Extreme lines (±10000 spread, 1000 total): float underflow manufactured
  p=0.0 → now refused by the degenerate guard (`DEGENERATE_PROBABILITY_REFUSED`).
- Rounding hole: raw p=5.4e-9 reported as clean 0.0 → guard now runs on
  rounded reported values (found by red-team, fixed).
- Decimal-odds confusion (1.91 as American) → rejected `ODDS_INVALID`, never
  mispriced. Zero odds → rejected. +100/-100 sign handling verified identical.
- Null/missing odds/line/side/market/sport → explicit blocked reasons.
- Contradictory sides (OVER+UNDER same line) price coherently (mass = 1);
  duplicate rows price identically; 10-row pathological board (dups,
  contradictions, extremes, nulls, bad bands) runs without crashing.
- Ambiguous team identity ("New York" → Yankees+Mets) → refused, never guessed
  (F5 StatsAPI ID resolution).
- F5 with <10 prior games → blocked; F5 with wrong sport → blocked.
- Insufficient-history and wrong-shape payloads → blocked with reason codes.

## Known limitations / follow-ups for the coordinator

1. Validation means omit injury/form/weather/pitcher context (margin-proxy
   only); fails are large enough to stand, but a full-context re-run is valid.
2. The base total engine (all sports) likely shares the margin-proxy total
   weakness — needs its own harness validation (out of Phase 7 scope).
3. F5 pricing needs live StatsAPI access at card time; offline/manual mode
   fails closed with `F5_TEAM_IDENTITY_UNMATCHED`.
4. Quarter team-total sd (`sd_total/2/√2`) and quarter variance scaling are
   declared, not fitted; they failed — do not revive without a verifying model.
5. Market-baseline leg: re-run with archived DK prices when the Odds API
   archive (now authorized, Actions-side) covers these markets.
6. Anytime-TD unblock needs verified rush/rec TD history (Phase 3 or decoder
   extension with unambiguous stat names).
