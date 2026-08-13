# SportsEdge NRFI/YRFI V6 Forward-Shadow Protocol

Committed before any 2026-08-13 MLB game outcome is observed by this V6 lane.

## Purpose

NRFI/YRFI V5 remains failed and ineligible. Its untouched-2025 overall calibration z-statistic was 2.56165 against the frozen maximum 2.5. This document does not alter, reinterpret, or supersede that failed result. V6 is a new model-development lane and must earn deployment on genuinely future observations.

## Immutable chronology

- Development outcomes may include data with game date <= 2026-08-12 only.
- No outcome, final score, first-inning result, closing price, or post-first-pitch information from 2026-08-13 onward may influence V6 model fitting, feature selection, hyperparameter selection, calibration selection, or acceptance-threshold selection.
- Forward shadow begins with games dated 2026-08-13.
- Every forward prediction must be persisted before first pitch with artifact hashes, feature-contract hash, source cutoff, game identity, starter identities, lineup provenance, and generated timestamp.
- Outcomes are attached later by a separate scorer. Missing or late predictions are not backfilled.
- Same-day completed games may not update model parameters or feature transformations used for later games on that same date.

## Model_P independence

Sportsbook odds, implied probabilities, consensus lines, market movement, third-party predictions, and public model outputs are prohibited from V6 Model_P features, model fitting, calibration, and model selection. Prices may be joined only after Model_P exists for EV/execution.

## Frozen V6 feature families

V6 research may use only prior-only members of these predeclared families:

1. Starting-pitcher contact suppression and expected-contact quality from the frozen SportsEdge Statcast transformer.
2. Starting-pitcher strikeout, walk, handedness, recent workload/rest, and expected first-inning availability from official MLB/Statcast-derived prior data.
3. Batting-order quality with slots 1-3 required and slots 4-9 permitted when a complete projected or confirmed 1-9 order is available; lineup provenance must be recorded.
4. Batter expected-contact quality, Barrel%, Hard-Hit%, exit velocity, handedness/platoon, and pitch-family matchup features using prior-only observations.
5. Park, weather, roof, and home-plate umpire run-environment features only when timestamped pregame and actually present in the serialized feature contract.
6. Opener/bulk-pitcher identity handling; a probable starter may not be treated as a conventional starter when opener rules classify otherwise.
7. Calendar/rest terms already available to SportsEdge, provided they are cutoff-safe.

No new predictive feature family may be added after forward-shadow outcomes begin without creating a new version/protocol.

## Candidate architecture

Model development may compare a small predeclared family of first-inning probability estimators using only pre-2026-08-13 development data:

- regularized logistic model;
- gradient-boosted tree model with monotonicity only where scientifically justified;
- calibrated ensemble of those two models.

Selection must be completed and the final serialized artifact hash frozen before any forward-shadow outcome is scored for deployment eligibility. The production artifact must expose its literal ordered feature vector; metadata claims alone cannot satisfy feature use.

## Forward-shadow acceptance gates

Deployment evaluation begins only after BOTH minimum evidence conditions are met:

- at least 14 full calendar days after 2026-08-13, and
- at least 200 eligible pregame MLB game predictions with subsequently observed first-inning outcomes.

Until both conditions are met, state is MODEL_NOT_ELIGIBLE / FORWARD_SHADOW_INSUFFICIENT_SAMPLE.

Once minimum evidence is met, ALL of these frozen gates must pass:

1. Overall absolute calibration z <= 2.50.
2. For probability buckets [0,.2), [.2,.4), [.4,.6), [.6,.8), [.8,1], every bucket with n >= 75 must have absolute calibration z <= 2.50.
3. Overall Brier score must be <= the locked V5 development comparator Brier + 0.0010, where the comparator is computed on the exact same forward rows using V5 predictions frozen before first pitch. If V5 cannot emit a valid prediction for a row, that row is excluded from the paired comparator but remains in V6 absolute-calibration evaluation.
4. Overall log loss must be <= the locked V5 development comparator log loss + 0.0020 on paired rows.
5. Prediction coverage must be >= 90% of games for which required official/projection sources were legitimately available before first pitch. Source-unavailable games are BLOCKED, not imputed.
6. No chronology, identity, artifact-hash, feature-contract, or sportsbook-contamination violation is permitted. Any such violation invalidates the affected row; systemic violations block deployment.

No threshold above may be relaxed after forward outcomes are observed. Failure creates a new version, never a threshold edit.

## Price-feed separation

Model validation does not imply bet eligibility. A production NRFI/YRFI bet additionally requires a reachable legitimate first-inning price source, exact game/market/side binding, and freshness TTL. If Model_P is eligible but no legitimate price is reachable, the Full Model output must report NO_PRICE.

## Deployment evidence required

NRFI and YRFI become eligible only when CI binds all of the following to one exact commit/artifact set:

- this protocol SHA-256;
- final V6 model artifact SHA-256;
- serialized feature contract;
- prediction ledger SHA/manifests;
- forward-shadow evaluation report satisfying every frozen gate;
- live feature-parity test;
- runtime attestation proving Model_P independence from sportsbook data.

Anything less remains MODEL_NOT_ELIGIBLE.