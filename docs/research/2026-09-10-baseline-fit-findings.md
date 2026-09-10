# Baseline fit findings — 2026-09-10

Status: empirical research record only. These results do not create a production model, Model_P artifact, Truth Gate pass, or OFFICIAL betting eligibility.

## First fitted outputs

The first hosted fit used free historical result sources and produced held-out outputs for MLB, NFL, and CFB.

Observed cross-validated ridge alphas:

- MLB margin: 300.0
- MLB total: 300.0
- NFL margin: 100.0
- NFL total: 100.0
- CFB margin: 300.0
- CFB total: 0.1

The assumed production alpha of 10.0 is therefore unsupported by this first empirical run. No production alpha should be frozen from these results alone.

## Placebo review

Shuffled-label holdout R2 values were:

- MLB: negative/slightly negative
- NFL margin: +0.0127
- NFL total: +0.0036
- CFB margin: +0.0009
- CFB total: -0.0009

The small positive football placebo values are not by themselves proof of leakage, but they require review. The CFB margin result is especially sensitive to talent-gap effects because the baseline uses rolling points for/against and has no opponent-strength control.

## Requested diagnostics

### NFL closing-market benchmark

The corrected report uses raw nflverse spread_line values. Across 272 holdout games:

- Margin model RMSE: 13.2120
- Closing spread RMSE: 12.3595
- Spread-line correlation with actual home margin: +0.4921
- Total model RMSE: 13.3600
- Closing total RMSE: 13.1325

The positive correlation confirms the raw spread_line orientation. The model loses to the closing spread by about 0.853 RMSE and loses to the closing total by about 0.228 RMSE. NFL does not pass the first market-relative screen.

### CFB close-game split

For 415 CFB holdout games decided by under 14 points:

- Full margin model R2: 0.3587
- Under-14 margin model R2: -0.6249
- Under-14 model RMSE: 10.2777
- Under-14 mean-baseline RMSE: 8.0628

The strong full-sample CFB margin result does not survive the close-game filter. This supports the talent-gap/blowout explanation and disqualifies this baseline from betting-model certification.

## Decision

- Keep all three fitted outputs research-only.
- Do not freeze alpha 10.0 or any replacement alpha yet.
- Do not certify NFL margin or total; both lose to the closing market in this baseline test.
- Do not certify CFB margin; it is worse than the mean on close games.
- Treat CFB total alpha 0.1 as a noise-sensitive CV result pending robustness checks.
- Treat MLB as research-only pending its own market-relative and calibration evidence.

The baseline report remains research-only until the full calibration, provenance, and Truth Gate requirements are complete.


## Post-holdout protocol

The 2025 NFL measurements are validation results and must not be reused for feature selection. The initial 2019-only development result is historical evidence from a superseded design, not the active search window.

The frozen immediate search window is now 2017-2019, with training restricted to 2010-2016. The fitter reads and validates this window from \`config/nfl_research_search_policy_v1.json\`; the workflow no longer supplies a competing holdout range.

- Reserved future holdout: the completed 2026 NFL season, evaluated only after the feature set is frozen.
- Current feature-search attempts allowed: 10 distinct feature specifications.
- A same-window baseline control is pre-registered and budget-neutral because it calibrates the denominator; any feature selection or tuning consumes an attempt.
- Primary metric: closing-market RMSE.
- Placebo control: deterministic 200-shuffle training/CV null before feature evaluation.
- Do not compare metrics across holdout definitions; compare control versus candidate within 2017-2019.
- No widened-window rerun has been interpreted yet.

## Frozen NFL search policy

Decision: use the widened 2017-2019 window for immediate development, with 2010-2016 training. Reserve the completed 2026 season as the later forward holdout; it is not used during feature selection.

- Feature-search budget: 10 distinct feature specifications.
- Every candidate evaluated against the frozen 2017-2019 window counts, including discarded or failed candidates.
- The matched baseline control is budget-neutral and was declared as calibration, not a feature search.
- Primary metric: closing-market RMSE.
- Placebo control: deterministic 200-shuffle training/CV null before each new feature evaluation.
- 2025 and the original 2019-only result are historical validation records, not search denominators.
- Policy file: \`config/nfl_research_search_policy_v1.json\`

## Chronology correction

The earlier 2010-2018 → 2019 design was superseded because a single-season holdout could not resolve a prospective improvement reliably. The active design is 2010-2016 training followed by 2017-2019 validation, approximately three seasons of holdout data. The fitter fails closed if the policy window is invalid, if training overlaps the holdout, or if the workflow omits a required season.

CFB and MLB feature searches are blocked until each has its own widened chronological holdout and matched control. All outputs remain research-only: no production artifact, Model_P, Truth Gate pass, or OFFICIAL betting eligibility.
