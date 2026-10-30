# MLB NRFI/YRFI first-inning starter exposure, forward-market prereg v2 (DRAFT)

Version label `MLB_NRFI_FIRST_INNING_STARTER_V2`. **DRAFT, NOT FROZEN.** PAPER / 0u. It incorporates `COMMON_V2_TERMS.md` (T1–T7) by reference.
- Predecessor: `docs/preregs/MLB_NRFI_FIRST_INNING_STARTER_PREREG_20261013.md` (v1, unevaluated, kept as history).

## 1. Candidate (carried from v1 §2 unchanged)
P(YRFI) = 1 − P(away 1st = 0) * P(home 1st = 0).
- Each half is NB2 inning-1 runs with mu = r_T,1 * a_S:
  - r_T,1 is the batting team's strictly-prior inning-1 rate (last 60 games, 370-day lookback, Gamma-shrunk, prior weight 40 games).
  - a_S is the opposing starter's strictly-prior first-inning runs-allowed index (370 days, prior weight 15 starts).
- Dispersion k is the league MLE on training data only.
- Starters come from `mlb_pregame_starter_adapter` only (T6).
- Batting order is not used (no verified pregame lineup capture); this is a stated limit.

## 2. Data and population
- Data as in F5 v2 §2.
- Population: 2027 MLB regular-season games with a completed first inning (both halves).

## 3. Legs (both must pass; T1)
- **(a) vs existing model:** production `mlb_first_inning_empirical_jeffreys_m30_v2` (T3). Log loss on the YRFI binary; the 95% date-clustered CI of (candidate − m30) must have upper < 0. This replaces v1's B1 (`..._poisson_jeffreys_v1`), which was no longer production after #1596.
- **v1's B0** (league strictly-prior YRFI rate, Jeffreys) is retained as a reported diagnostic.
- **(b) vs market (T4):** the de-vigged NRFI/YRFI close (two-way multiplicative). The 95% date-clustered CI of (candidate − market) log loss must have upper < 0.
- **Calibration guard (carried from v1):** calibration slope must be in [0.8, 1.2]. Otherwise FAIL.
- **Secondary (reported):** Brier, 10-bin ECE (method `scripts/research_mlb_f5_nrfi_tightening.py::ece`), CLV and ROI per T4.

## 4. Verdict
Same as F5 v2 §6.

## 5. Changes vs v1
Items 1–6 as in F5 v2 §7. Item 1 here is replacing the stale B1 with production m30_v2. Item 6 here is the date-clustered bootstrap and 2026 RS being training-only.
