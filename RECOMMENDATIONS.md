# Open-Source Betting-Model Sweep — Recommendations (2026-10-11)

Survey of public sports-betting model repos for techniques, data sources, or
tooling worth adopting into SportsEdge. Adoption bar: fits the verified-data,
research-only, fail-closed architecture AND improves on what's there.
No code was vendored from any repo — only techniques were studied and
re-implemented where adopted.

**Adopted in this branch:** `sportsedge/research/factor_gate.py` + tests
(`tests/test_factor_gate.py`, 20/20 pass) — forward selection with a
minimum-gain gate plus test-set ablations, adapted from sujaynadkarni's
nfl-prediction methodology. Research-only protocol layer; touches no
production pricing path, so no harness model-change verdict applies.
No new DK market is enabled by this adoption → no market-coverage matrix action.

**Standing constraints honored throughout:** public verified data only, no
Odds API, fail closed, research-only with no staking authority.

## 1. sujaynadkarni/nfl-prediction — ADOPTED (technique)

https://github.com/sujaynadkarni/nfl-prediction

An NFL model built on free nflverse/nflfastR data with the most honest
methodology found in this sweep: forward feature selection with a minimum-gain
threshold on validation Brier, full test-set ablations of every factor, and
comparison against both an Elo-only baseline and Vegas. Most valuable is its
published "things tested and rejected" list: rest days/bye weeks/short weeks
(no gain — Thursday games put *both* teams on short rest), travel distance
(made predictions worse), and gradient-boosted trees (worse probabilities than
the linear model; ~285 games a season is not much data).

Adopted: the selection/ablation discipline as `sportsedge/research/factor_gate.py`.
Recommended follow-ups:
- Add a **naive-model baseline leg** to the backtest harness alongside the
  existing-vs-market legs (their Elo-only comparison is the template). A
  candidate that can't beat a trivial baseline shouldn't reach production.
- Adopt their **rejected-factor watch**: six rejected factors re-tested
  automatically on every run, logged, never auto-promoted. `retest_rejected()`
  in the adopted module is the mechanism; wire it into the harness report once
  it merges.
- Their XGBoost-negative result is direct evidence for the standing ML
  caution: any tree/ML candidate must beat the linear/empirical model in the
  harness, not just the incumbent.

## 2. pacman1984/backtestbuddy (MIT) — NOT ADOPTED

https://github.com/pacman1984/backtestbuddy

A clean sports-betting backtest framework (walk-forward CV, fixed-stake/Kelly/
ValueBet strategies, Sharpe/Sortino/Calmar/drawdown metrics with documented
formulas and independent numeric tests).

Why not adopted: its strategy layer is staking machinery (Kelly sizing, unit
staking, bankroll simulation). SportsEdge is research-only with no staking
authority — adopting stake-sizing would contradict the architecture. Its
metrics overlap what SportsEdge already has (ECE exists in three modules; the
harness has Brier/log-loss/calibration).
Recommendation: none for production. If paper-card research evaluation ever
wants risk metrics, lift their formula-test discipline (documented formulas +
independent numeric tests), not the staking strategies.

## 3. Veedubin/quantitative-sports — NOT ADOPTED

https://github.com/Veedubin/quantitative-sports

Walk-forward validation config, CLV tracking, and a distribution-model menu
(EmpiricalCDF / Gamma / LogNormal / NegativeBinomial with a fit-quality-based
`DistributionSelector`), plus rest-days and venue-splits analyses.

Why not adopted:
- Walk-forward validation already exists in the SportsEdge harness with
  no-lookahead enforcement.
- CLV tracking requires historical closing lines — Odds API territory,
  excluded by Isaac's standing choice.
- The NFL XGBoost model trains on a **synthetic placeholder dataset** by
  default ("real training would come from nflfastR play-by-play" — aspirational);
  no published backtest results on real data. Nothing to adopt there.
Recommendations:
- The `DistributionSelector` *methodology* (fit several tail distributions,
  pick by fit quality on held-out data) is worth evaluating for player-prop
  tail modeling — gated on a harness verdict before any production use.
- Their rest-days / venue-splits analyses are free-factor candidates;
  methodology reference only, for Phase 2 (free factors).

## 4. notaparlaymaker/sportsbetlang (VigScript) — NOT ADOPTED

https://github.com/notaparlaymaker/sportsbetlang

Betting scripting language with odds math, bankroll simulation, and backtesting
of `.vig` strategy scripts.

Why not adopted: its devig is a single basic method — strictly less
sophisticated than SportsEdge's frozen policy devig (multiplicative/power/Shin
with longshot sensitivity gating). Its bankroll/Kelly/parlay tooling is
staking-adjacent and incompatible with research-only. Its CLV needs closing
odds (excluded). No new technique found that improves on what's here.
Recommendation: none in code. Its docs principle — "risk transparency required
in reports" — already matches the research-card posture.

## 5. ngalstyan/bayesian-pga-tour-matchup-prediction-system — CAUTIONARY TALE

https://github.com/ngalstyan/bayesian-pga-tour-matchup-prediction-system

A hierarchical Bayesian golf model whose *published* backtest (+6.0% ROI) was
later invalidated by a lookahead bug: the data source reuses `event_id` across
annual editions of the same tournament, the backtest cache was keyed by
`event_id` alone, and ~47% of one year's bets were priced with models trained
on future data. Fixed with composite `(event_id, year)` keys end-to-end plus
regression tests.
Recommendation: run a one-time audit of SportsEdge cache/fixture keys for
single-key temporal collisions (game IDs reused across seasons, cache keys
missing a season/year component). Adopt composite (event, season) keys
everywhere as the standard. This is the exact bug class that silently produces
fake edges.

## 6. penaltyblog (via alexandrosh8/sharp-ev-picks research doc) — RECOMMENDED

https://github.com/alexandrosh8/sharp-ev-picks (research doc) → penaltyblog PyPI package

penaltyblog implements 7 devig methods (SportsEdge has 3: multiplicative,
power, Shin). A third party parity-tested penaltyblog 1.11.0's devig to 1e-8
in CI.
Recommendation: evaluate adding **logarithmic devig** (and/or odds-ratio) to
the devig *sensitivity set* for longshot fail-closed gating. Production
estimator stays frozen; a wider sensitivity set can only make the longshot
spread gate stricter, never looser. Needs a harness verdict and parity tests
before adoption. Low priority.

## 7. FranciscoOrtizTena/NFL-elo-model — REFERENCE ONLY

https://github.com/FranciscoOrtizTena/NFL-elo-model

Elo + EPA NFL model with validation and free data. Methodology is compatible
but adds nothing over SportsEdge's empirical NFL path; useful as a reference
implementation for the naive-baseline leg recommended in §1.

## 8. meng-coolman/pitchquant — OUT OF SCOPE

https://github.com/meng-coolman/pitchquant

Soccer-only (Poisson/Elo-band). SportsEdge has no soccer lane. Skipped.

## Data-source notes

- **nflverse / nflfastR**: free, stable, already the standing choice for NFL
  tracking-data investigation (Phase 3). This sweep confirms it's the
  community standard for free NFL data (used by nfl-prediction and
  quantitative-sports).
- Nothing found that provides free, stable *closing-line* history without the
  Odds API — the CLV leg stays conditional, as Isaac chose.

## Known limitations of this sweep

- Repo quality in this niche is uneven; several "published backtest results"
  (notably bflinkdesign/nfl-betting-system's +428% ROI claim) show classic
  overfit/backtest-marketing signatures and were excluded from consideration.
- The factor-gate module is validated by its own test suite on synthetic
  records; it has not yet been exercised against a real harness run because it
  is research tooling (no production pricing path changed), not a model change.
- quantitative-sports has no LICENSE file at root; sportsbetlang's license is
  unclear. No code was copied from any repo, so this is attribution-only.
