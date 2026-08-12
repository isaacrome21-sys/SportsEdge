# Pitcher BB v5 Predeclared Rescue Protocol

Recorded before any BB-v5 fit is executed.

- Recorded UTC: 2026-08-12T03:20:00Z
- Scope: PITCHER_BB only
- Status at declaration: BB-v4 blocked because the 1.5-walk threshold failed 2026 aggregate calibration; frozen BB-v2 external comparison also failed and is retired as a deployment candidate.
- Deployment effect of this document: NONE. This protocol does not change `config/deployments.json`.

## Evidence-status constraint

The 2026 data through 2026-08-10 has already been inspected in detail, including the 1.5-threshold miss and its concentration in the prior-pitcher-BB-rate 8%-10% band. Therefore no BB-v5 result on that period may be described as a pristine, untouched, or independent model-selection holdout. Any 2026 re-score is confirmatory/post-hoc evidence only.

## Candidate family locked before fitting

BB-v5 must be the smallest auditable change to BB-v4:

1. Keep the BB-v4 cutoff-correct, source-bounded feature builder unchanged.
2. Keep the BB-v4 HistGradientBoosting threshold models unchanged for 0.5, 1.5, 2.5, and 3.5.
3. Keep the existing 2025 global Platt calibrators unchanged for 0.5, 2.5, and 3.5.
4. Only the 1.5 threshold may receive an additional calibration layer.
5. The added 1.5 calibration layer may use only:
   - the existing globally calibrated 1.5 probability; and
   - the pregame prior-pitcher BB/BF feature `pit_bb_hist`.
6. Predeclared `pit_bb_hist` bands are fixed as: <0.06, [0.06,0.08), [0.08,0.10), [0.10,0.12), >=0.12.
7. No other new features, interactions, thresholds, sportsbook fields, opponent-derived postgame fields, manual offsets, or hand-tuned probability bumps are permitted in this candidate family.
8. The narrow calibration layer must be monotone in the base probability within each band and must clip output to [0.001, 0.999].
9. If the narrow layer fails the acceptance rules below, BB-v5 fails. The protocol must not silently expand to a new count/distribution model under the same version or evidence claim.

## Fitting protocol

The band-aware 1.5 calibration layer is fit only on 2025 rows using date-blocked cross-fitting for internal assessment. All features for a game must come from the prior-day frozen snapshot and all source rows must satisfy the declared request interval.

For the final frozen BB-v5 candidate, the 1.5 calibration layer may then be fit on all eligible 2025 rows after its functional form and acceptance rules have been locked by this document. No 2026 labels may be used for parameter fitting, band definition, feature selection, or tolerance selection.

## Acceptance rules

### A. 2025 date-blocked cross-fit gate

For the 1.5 threshold:

- aggregate calibration z <= 2.0;
- every probability bucket with n >= 30: z <= 2.5;
- every predeclared `pit_bb_hist` band with n >= 75: z <= 2.5;
- Brier score must not worsen versus BB-v4 by more than 0.001 absolute;
- log loss must not worsen versus BB-v4 by more than 0.002 absolute.

For the 0.5, 2.5, and 3.5 thresholds, outputs must be byte-for-byte/model-path identical to BB-v4; any change is a hard failure.

### B. 2026 through Aug. 10 confirmatory gate — explicitly post-hoc

This period is not a pristine holdout. It is used only to test whether the predeclared narrow fix behaves consistently with the already-observed failure structure.

Required:

- 1.5 aggregate z <= 2.0;
- 1.5 probability-bucket max z <= 2.5;
- every predeclared `pit_bb_hist` band with n >= 75: z <= 2.5;
- the [0.06,0.08) band absolute calibration gap must not worsen by more than 1.0 percentage point versus BB-v4;
- the [0.08,0.10) band absolute calibration gap must improve by at least 2.0 percentage points versus BB-v4;
- 0.5, 2.5, and 3.5 metrics and predictions must remain unchanged from BB-v4 apart from deterministic serialization metadata.

Passing this section does NOT by itself authorize deployment because the period was inspected before candidate construction.

### C. Fresh forward-shadow gate required for deployment

BB-v5 remains non-deployable until a genuinely future, not-yet-observed sample beginning after 2026-08-11 is accumulated under the frozen candidate.

Minimum deployment gate:

- at least 300 starter rows total;
- at least 50 rows in the [0.08,0.10) prior-BB-rate band, otherwise continue shadow collection;
- 1.5 aggregate z <= 2.5;
- every predeclared rate band with n >= 40: z <= 3.0;
- no other threshold may newly fail its existing aggregate <=2.5-SE gate;
- no model, calibrator, band definition, tolerance, or feature definition may change after the first shadow prediction is recorded.

If the minimum row count is reached but the 8%-10% band count is not, BB remains blocked until the band minimum is reached.

## Failure semantics

Any failure leaves `PITCHER_BB` blocked. No partial deployment by threshold is permitted unless a separate, explicitly predeclared market-contract change is reviewed and tested first.

If this narrow calibration candidate fails, the next candidate must use a new version and a new predeclared protocol before any fitting. A count/distribution model would be such a new candidate; it is explicitly out of scope for BB-v5.

## Audit labels

- 2025 cross-fit: `MODEL_DEVELOPMENT_CROSSFIT_EVIDENCE`
- 2026 through Aug. 10: `POST_HOC_CONFIRMATORY_NOT_PRISTINE_HOLDOUT`
- post-Aug. 11 frozen shadow sample: `FRESH_FORWARD_SHADOW_EVIDENCE`
- deployment eligibility may change only after the forward-shadow gate passes and runtime/live-feature parity is separately verified.
