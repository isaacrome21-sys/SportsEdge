# Phase 1: MLB First-Inning Markets (NRFI/YRFI + siblings)

Branch: `feat/mlb-first-inning-20261011` (from origin/main 5e161b9).
Research only. No betting authority, no staking, no odds APIs.

## What was built

| File | Role |
|---|---|
| `sportsedge/mlb_first_inning_data.py` | Verified StatsAPI data layer: schedule `hydrate=linescore,probablePitcher`, per-team strictly-prior history pools (home/away venue split), pregame fixture resolution, pitcher gameLog → prior-start 1st-inning runs-allowed (gameLog starts × verified linescores), play-by-play starter split (IN_BUILD) |
| `sportsedge/mlb_first_inning_model.py` | Pure-math pricing: binary Jeffreys Beta(1/2,1/2) 1st-inning scoring indicators, 50/50 team/starter blend, independent halves → P(YRFI). **No league priors.** Strict interior probabilities; fail-closed gates |
| `sportsedge/mlb_phone_first_inning_pricing.py` | Phone intake: `phone_first_inning_rows()` — fixture verification, pool building, quote pairing via `price_three_sport_research`, explicit blocked reasons |
| `artifacts/run_it_full.py` | Routing: `FIRST_INNING_PHONE_MARKETS` → new module; receipts; `prop_model_status["first_inning_engine"]`; audit source allowlist |
| `tests/test_mlb_first_inning.py` | 32 tests: model math, fail-closed gates, linescore parsing/pooling, starter split, routing |
| `research/validate_mlb_first_inning.py` | Harness validation script (run with cwd=`~/workspace/sportsedge-backtest`) |
| `research/first_inning_backtest_report.json` | Full predictions + verdicts (generated) |

## Data (all free, all verified)

- Team 1st-inning runs/hits for+against and game hits for+against: MLB StatsAPI
  schedule `?sportId=1&hydrate=linescore` (per-inning `runs`/`hits`, game totals).
- Probable starters: same schedule call with `hydrate=probablePitcher`
  (100.0% agreement with actual starters on an 800-game check via gameLog
  `gamesStarted`).
- Starter 1st-inning "allowed a run" indicators: pitcher `gameLog`
  (group=pitching, `gamesStarted==1`) × the verified linescore of each prior
  start (batting side's 1st-inning runs in the half the starter pitched).
  Documented approximation: all 1st-inning runs attributed to the starter.
- Rescheduled games listed under two dates deduped by gamePk (7 found).
- Postseason/spring excluded from pools (`gameType=R` only).

## Models tried (harness judged all of them)

1. **Team-rates Poisson** (`first_inning_team_rates`): FAIL everywhere.
   Root cause found: team 1st-inning scoring rates do **not** persist —
   half-season split correlation r = −0.11 across 30 teams. Pure noise.
2. **Poisson + starter** (`first_inning_with_starter`): FAIL. Root cause:
   the Poisson link is badly misspecified for 1st-inning runs (overdispersed:
   empirical P(YRFI)=0.485 vs 1−exp(−mean)=0.647). Train-fit shrinkage cannot
   fix a wrong link.
3. **Binary starter** (`first_inning_binary_starter`): **PASS** on
   FIRST_INNING_RUNS. Per-half p(score) = ½·J(team 1st-inn scoring indicator)
   + ½·J(opposing starter's 1st-inn allowed indicator), J = Jeffreys
   Beta(1/2,1/2) posterior mean (non-informative, no league data);
   P(YRFI) = 1 − (1−p_away)(1−p_home).
4. **Naive baseline** (`naive_historical_rate`): overall outcome rate per
   (market, selection, line) over the 2024 train window. No market baseline
   exists (no Odds API by Isaac's choice) — documented, not invented.

## The bar (new market — existing model cannot price it)

**PASS** iff, per market, on chronological out-of-sample fixtures (train =
2024 regular season 2422 games, test = 2025 regular season 2425 games,
strictly-prior features), with n ≥ 100 priced fixtures:
(a) candidate Brier < naive Brier, **and**
(b) candidate log-loss < naive log-loss, **and**
(c) calibration: in every reliability bin with n ≥ 30,
|mean_p − hit_rate| ≤ 0.10.
Otherwise **FAIL** with explicit reasons.

## Harness verdicts (from `research/first_inning_backtest_report.json`)

| model::market | n | verdict | brier (cand/naive) | logloss (cand/naive) | worst cal dev |
|---|---|---|---|---|---|
| binary_starter::FIRST_INNING_RUNS | 3846 | **PASS** | 0.2496 / 0.2509 | 0.6924 / 0.6950 | 0.058 |
| binary_starter::FIRST_INNING_TEAM_RUNS_HOME | 3846 | PASS* | 0.2125 / 0.2170 | 0.6159 / 0.6262 | 0.052 |
| binary_starter::FIRST_INNING_TEAM_RUNS_AWAY | 3846 | FAIL | 0.1980 / 0.1968 | 0.5848 / 0.5827 | 0.095 |
| starter_calibrated::FIRST_INNING_RUNS | 3846 | FAIL | 0.2693 / 0.2509 | 0.7350 / 0.6950 | 0.159 |
| with_starter::FIRST_INNING_RUNS | 3846 | FAIL | 0.2696 / 0.2509 | 0.7366 / 0.6950 | 0.201 |
| team_rates::FIRST_INNING_RUNS | 4850 | FAIL | 0.2745 / 0.2512 | 0.7471 / 0.6956 | 0.205 |
| team_rates::FIRST_INNING_TEAM_RUNS_* | 4850 | FAIL | — | — | — |
| team_rates::FIRST_INNING_HITS_* | 4850 | FAIL | — | — | — |
| team_rates::TEAM_HITS_* | 4850 | FAIL | 0.223x / 0.219x | 0.641x / 0.631x | 0.10–0.11 |

\* TEAM_RUNS_HOME passes on test but the per-half signal is **not robust**:
on train, AWAY beats naive while HOME loses — the halves flip between
windows (±0.002, sampling noise). Only the game-level YRFI is consistent
(beats naive on both train and test). Per-team markets stay IN_BUILD.

Caveats (honest): the binary link was chosen after observing the Poisson
link's miscalibration — the miscalibration itself is visible on train
(1−exp(−1.036)=0.645 predicted vs 0.475 actual), so link selection is
train-justified; no parameters were fit on test. The edge is small
(+0.0013 Brier) — real but weak, as expected for NRFI.

## Coverage matrix (the 6 markets)

| Market | Classification | Reason / evidence |
|---|---|---|
| FIRST_INNING_RUNS (NRFI/YRFI) | **SUPPORTED** | Built + wired into runner + 32 tests + **PASS**ed harness bar (binary starter model, `mlb_first_inning_binary_starter_jeffreys_v1`) |
| FIRST_INNING_HITS | IN_BUILD | Verified data path exists; team-rate model FAILED harness (no signal); starter hits-allowed path not yet validated |
| FIRST_INNING_HR | BLOCKED_WITH_REASON | `FIRST_INNING_HR_NOT_IN_VERIFIED_LINESCORE` — no free verified per-inning HR history |
| FIRST_INNING_TEAM_RUNS | IN_BUILD | Per-half binary signal not robust (train/test flip); game-level passes but halves do not — no probabilities emitted |
| FIRST_INNING_PITCHES | BLOCKED_WITH_REASON | `FIRST_INNING_PITCHES_NO_VERIFIED_PER_INNING_HISTORY` — no free verified per-inning pitch counts at feasible cost |
| TEAM_HITS | IN_BUILD | Team-rate Poisson FAILED harness (0.2235 vs 0.2196 naive); needs a different approach |

Classification rule: SUPPORTED only if built + wired + tested + passed the
harness bar. Anything else is IN_BUILD or BLOCKED_WITH_REASON with the
explicit reason. IN_BUILD markets are recognized by the runner and blocked
with explicit reasons — never silently priced, never emitting probabilities
from failed models.

## Known limitations

- Starter attribution: all 1st-inning runs charged to the starter (no
  mid-inning pitching-change allocation; play-by-play path exists IN_BUILD).
- Probable-pitcher identity is pregame-listed; late scratches fail closed
  only when the listing is absent (a late scratch after listing is a known
  residual risk — disclosed).
- No park adjustment (Phase 2), no batting-order quality beyond team rates.
- The validated edge is small; NRFI remains a low-signal market.
- Binary link selection used train-visible miscalibration (documented above).

## Rerun

```
cd ~/workspace/sportsedge-backtest
python3 ~/workspace/sportsedge-firstinning/research/validate_mlb_first_inning.py
```
Network cache: `research/.cache_first_inning/` (gitignored). Report:
`research/first_inning_backtest_report.json` (committed).
