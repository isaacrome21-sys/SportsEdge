# SportsEdge Pitcher BB V6 Forward-Shadow Protocol

Committed before any 2026-08-13 MLB game outcome is observed by this V6 lane.

## Purpose

Pitcher BB V5 remains ineligible. The V5 narrow 1.5-walk calibration attempt failed fail-closed at `BB_V5_NON_MONOTONE_SLOPE`; its acceptance tolerances are not changed here. V6 is a new forward-shadow lane with a structurally monotone calibration design and genuinely future deployment evidence.

## Immutable chronology

- Development outcomes may include game dates <= 2026-08-12 only.
- Outcomes from 2026-08-13 onward are forward-shadow only and may not influence fitting, feature selection, calibration selection, hyperparameters, thresholds, or model-version decisions.
- Predictions must be written before first pitch and before the pitcher's first pitch, with game/pitcher identity, probable/confirmed starter status, artifact hashes, feature-contract hash, source cutoff, generated time, and the probabilities for supported BB thresholds.
- Outcomes are joined later by a distinct scoring job. Missing pregame predictions are never reconstructed from postgame data.
- Same-day completed outcomes may not update parameters used for later games that date.

## Model_P independence

Sportsbook odds, implied probabilities, market lines, line movement, third-party predictions, or public trained-model outputs are prohibited from Model_P. Prices are downstream only.

## Frozen V6 feature families

V6 may use cutoff-safe prior observations from these families only:

1. Pitcher walk rate and strike/ball-control history with shrinkage/sample-size terms.
2. Pitch count, expected innings/batters faced, starter/opener role, rest, recent workload, and handedness.
3. Opposing projected/confirmed lineup walk propensity and plate-discipline aggregates, with exact lineup provenance.
4. Pitch-mix/arsenal control features from official Statcast-derived prior data, including prior-only zone/chase/contact proxies where reproducible.
5. Umpire/park/weather context only if pregame timestamped and literally present in the serialized model feature contract.
6. Team/opponent contextual terms already available to the frozen SportsEdge builder when cutoff-safe.

No new predictive feature family may be added after forward-shadow outcomes begin without a new version/protocol.

## Structurally monotone calibration

V6 will not fit an unconstrained logistic slope and then coerce a negative slope. Calibration candidates are limited to forms monotone by construction:

- pooled isotonic regression on base P(BB > threshold), with sample-weighting and clipping only at predeclared numeric probability bounds [0.001, 0.999];
- a monotone piecewise-linear calibrator whose knot order and monotonicity constraints are fixed before forward scoring.

Any banding/pooling rule must be selected using development data only and frozen in the serialized artifact before forward-shadow scoring begins. If minimum development support for a calibration region is not met, regions must be pooled according to a deterministic predeclared adjacent-pooling rule; no outcome-informed manual pooling is allowed after 2026-08-13.

The production artifact must expose the literal ordered feature vector and calibration object hashes. Metadata claims alone are insufficient.

## Supported threshold scope

V6 development may evaluate BB over 1.5 as the primary repair target. Other thresholds remain on their already-validated frozen path unless separately upgraded by a new predeclared protocol. V6 must not degrade an already-valid threshold merely to improve 1.5.

## Forward-shadow minimum evidence

Deployment evaluation begins only after BOTH:

- at least 14 full calendar days after 2026-08-13, and
- at least 150 eligible pregame starting-pitcher predictions with observed BB outcomes.

Before both conditions are met, status is MODEL_NOT_ELIGIBLE / FORWARD_SHADOW_INSUFFICIENT_SAMPLE.

## Frozen acceptance gates for BB > 1.5

ALL gates must pass:

1. Overall absolute calibration z <= 2.00.
2. Every probability bucket [0,.2), [.2,.4), [.4,.6), [.6,.8), [.8,1] with n >= 75 must have absolute calibration z <= 2.50.
3. Every predeclared pitcher-control band with n >= 75 must have absolute calibration z <= 2.50.
4. Overall Brier score must be <= the locked BB-v4 comparator Brier + 0.0010 on the same paired forward rows.
5. Overall log loss must be <= the locked BB-v4 comparator log loss + 0.0020 on the same paired forward rows.
6. Prediction coverage >= 90% of legitimately source-available eligible starters.
7. No chronology, starter-identity, artifact-hash, feature-contract, or sportsbook-contamination violation.

No gate may be relaxed after forward outcomes are observed. Failure requires a new version.

## Price/feed separation

A passing model is not automatically a bet. Pitcher BB prices must come from a legitimate reachable sportsbook feed or exact user-supplied price snapshot, be bound to pitcher/threshold/side, and satisfy freshness. Without price, the market reports NO_PRICE; without model eligibility, MODEL_NOT_ELIGIBLE.

## Deployment evidence required

Deployment requires CI-bound evidence for:

- this protocol SHA-256;
- final V6 artifact SHA-256;
- serialized feature/calibration contracts;
- immutable pregame prediction ledger manifests;
- forward-shadow evaluation satisfying every frozen gate;
- live feature parity and starter/opener identity checks;
- runtime attestation proving sportsbook independence.

Until then Pitcher BB remains MODEL_NOT_ELIGIBLE.