# Pre-registration: F5-specific dispersion / zero-inflation (MLB F5 team totals)

Committed **before** any fitting. Research only. The market baseline stays MISSING. F5 `eligible=false`, `config/deployments.json` and the registry are unchanged.

## Motivation
The thinning-coherent F5 NB (full-game r = 3.13, mean s·μ) loses to the naive baseline. See `MLB_F5_WALKFORWARD_20261013.md`: it overstates OVER, i.e. it underweights 0-run F5s.

## Candidate (fixed form)
- Team F5 runs ~ zero-inflated NB with mean m = s·μ preserved:
  - P(0) = π + (1−π)·NB(0; r_f5, m/(1−π))
  - P(k) = (1−π)·NB(k; r_f5, m/(1−π)) for k ≥ 1
- s and μ come from exactly the same point-in-time pipeline as the baseline: FINAL with linescore available by the slate cutoff (start + 6h), a 30-game team window, and `calibrated_full_game_means`.
- Free parameters: r_f5 ∈ {0.5, 0.75, …, 10.0} (step 0.25) and π ∈ {0.00, 0.01, …, 0.30}.

## Fitting (2024 only)
- Maximize the log-likelihood of the observed team F5 runs over all 2024 walk-forward team-game rows: each row's PIT mean m and observed runs.
- Ties go to the smaller π, then the larger r_f5.
- No 2025 data is used for fitting.

## Holdout (2025)
- Fixed (r_f5, π), applied in the same 2025 walk-forward. History is reset at the season start, exactly as in the baseline 2025 run.
- Lines 0.5 / 1.5 / 2.5, team F5 runs > line.
- Metrics: Brier and log-loss (p clipped to [1e-6, 1−1e-6]).
- Comparators: (a) naive = PIT league over-frequency; (b) the baseline thinned NB.

## Decision rule (fixed)
- **PASS_RESEARCH** iff the candidate's Brier < naive Brier **and** log-loss < naive log-loss at **all three** lines on 2025.
- Otherwise **FAIL**.
- Either way: no promotion, no eligibility change, and no re-fit on 2025.
- A FAIL is reported as-is. Any later variant needs a new pre-registration.
