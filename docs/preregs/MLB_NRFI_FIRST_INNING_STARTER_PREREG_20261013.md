# MLB NRFI/YRFI first-inning starter-exposure test — pre-registration (2026-10-13)

Status: PRE-REGISTERED, NOT EVALUATED. Research only; NRFI/YRFI stay
`eligible=false` (CANDIDATE_FORM). No activation, pricing, staking or backfill.

## 0. Inventory of existing code paths (no changes made)
- `sportsedge/mlb_first_inning_model.py` — Jeffreys-smoothed Poisson team-rate model
  (`price_game_first_inning_runs`, `_with_starter`, `price_first_inning_binary`).
- `sportsedge/mlb_first_inning_data.py` — verified StatsAPI linescore pools.
- `sportsedge/shared_first_inning_engine.py`, `mlb_phone_first_inning_pricing.py` —
  shared/phone pricing paths.
- `research/validate_mlb_first_inning.py`, `scripts/research_mlb_f5_nrfi_tightening.py`,
  `scripts/research_mlb_f5_nrfi_production_parity.py` — prior research (2025 holdout used).
- `scripts/score_nrfi_v6_forward_shadow{,_v2}.py`, `scripts/check_nrfi_durable_health.py`,
  `docs/nrfi_durable_evidence_recovery.md` — V6 forward shadow / durable settlement lane.
- `config/deployments.json` NRFI/YRFI: eligible=false, stage CANDIDATE_FORM.
- Existing starter input: retrospective; not a verified pregame binding.

## 1. Holdout hygiene
2024 and 2025 are burned for first-inning evaluation (tightening prereg used 2025).
Evaluation window: **2027 regular season only**, untouched.

## 2. Candidate (frozen)
P(YRFI) = 1 - P(away 1st = 0) * P(home 1st = 0). Each half: NB2 inning-1 runs with
mean mu = r_T,1 * a_S, where r_T,1 = batting team's strictly-prior inning-1 run rate
(last 60 games, 370-day lookback, Gamma-shrunk to league, prior weight 40 games) and
a_S = opposing starter's strictly-prior first-inning runs-allowed index (all starts in
370 days, shrunk to league with prior weight 15 starts). Dispersion k: league MLE on
training only. Starters come only from `mlb_pregame_starter_adapter`; unbound -> BLOCKED.
Batting order is NOT used (no verified pregame lineup capture); recorded as a limit.

## 3. Data
Free StatsAPI linescores/boxscores; training = 2021–2026 regular season, Final before
2026-10-13T00:00:00Z; strictly-prior-date features only. No paid data.

## 4. Baselines
- B0 league strictly-prior YRFI rate (Jeffreys).
- B1 current production model `mlb_first_inning_team_rates_poisson_jeffreys_v1` as committed.
- Market: paired DK NRFI/YRFI pregame captures if genuinely captured; else MISSING.

## 5. Metrics and rule
Primary: log loss on YRFI binary. Secondary: Brier, calibration (10 bins), ECE.
PASS_RESEARCH only if candidate beats B0 and B1 on log loss with game-level paired
bootstrap (2000, seed 20261013) 95% CI excluding zero, and calibration slope in
[0.8, 1.2]. Otherwise FAIL; no re-fit on 2027. Grants no eligibility.

## 6. Freeze
Implementation SHA-pinned before 2027-03-01; one evaluation after 2027 regular season.
