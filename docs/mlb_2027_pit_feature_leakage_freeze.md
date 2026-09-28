# MLB 2027 candidate lane — PIT feature eligibility and leakage freeze

Status: FROZEN SPECIFICATION — implementation and enforcement pending.

**NOT Model_P · NOT Truth Gate · NOT OFFICIAL**

## Scope

These rules govern feature eligibility for the single 2027 MLB candidate lane that produces moneyline, run-line, and full-game-total probabilities from one coherent full-game run distribution.

They define what information may exist at a model prediction timestamp (`as_of`) and what constitutes leakage. They do not fit a model, validate a model, create Model_P, or authorize promotion.

## Core PIT rule

A feature is eligible only when every observation needed to construct it was knowable at or before the prediction `as_of`.

For every dynamic input, `source_available_at <= as_of` must be provable from stored provenance.

If availability cannot be established, the input is **MISSING**. It must not be reconstructed from later knowledge.

Event/game timestamps alone do not prove information availability.

## Eligible feature families

### Starting pitcher
Eligible: starter identity announced and available by `as_of`; pitcher statistics derived only from appearances completed before `as_of`; workload/rest calculated only from appearances completed before `as_of`.

Ineligible: retrospective starter identity when not known by `as_of`; statistics containing any portion of the target game; later-confirmed starter changes projected backward.

### Lineup and batting order
Eligible: lineup/order actually published by `as_of`, with source provenance; a separately identified projected-lineup feature only if its projection itself was captured by `as_of`.

A projected lineup must never be relabeled as confirmed.

Ineligible: final lineup learned after `as_of`; batting-order information reconstructed from the completed game; substitutions or scratches learned after `as_of`.

### Starter workload
Rolling workload windows may contain only appearances completed before `as_of`. No innings, pitches, batters faced, velocity, injury consequence, or performance from the target game may enter its own prediction.

### Bullpen
Eligible bullpen state may use only games completed before `as_of`, including prior workload and rest.

Ineligible: target-game bullpen usage; reliever availability inferred from what subsequently happened in the target game; future games.

### Park
Static park characteristics are eligible when the value and effective version are known. Date-sensitive park/configuration changes require an effective date no later than `as_of`.

### Weather
Eligible weather is the forecast or observation actually available by `as_of`. The stored record must preserve retrieval/observation time and source. Final or later-observed game weather must not replace an earlier forecast in historical feature construction.

### Injuries and scratches
Eligible only when the underlying status/report was available by `as_of`. A later injury designation, scratch, activation, or roster transaction cannot be projected backward.

### Rolling player/team/Statcast features
Every rolling statistic must be lagged so that the target game contributes zero information to its own feature vector. Season-to-date and rolling-window aggregates end with the latest eligible completed game before `as_of`.

## Market-data separation

Sportsbook prices, implied probabilities, consensus prices, closing lines, and future line movement are not candidate-lane model features.

The candidate lane must produce its probability distribution independently of the sportsbook price against which it is evaluated.

Observed market quotes may enter only the downstream comparison/economics layer after model probabilities exist.

The closing price is a validation target, never a predictive feature for that same forecast.

Missing opposite-side prices remain **MISSING** and must never be inferred.

## Imputation

No imputation may use information occurring after `as_of`. An imputation statistic must itself be PIT-safe and fitted only from the permitted training history.

If an input required by the eventual readiness contract cannot be established PIT-safely, readiness fails closed rather than silently substituting future-derived information.

## Required provenance

Each training/prediction snapshot must be capable of recording, directly or through immutable source lineage:
- game identity;
- prediction `as_of`;
- feature/source identity;
- source observation or retrieval timestamp where applicable;
- effective event timestamp where applicable;
- transformation/version identifier;
- whether the value is observed, projected, static, or imputed.

Absence of required provenance makes the affected dynamic feature ineligible.

## Partition rule

Training, calibration, and validation construction must apply these same PIT rules.

The replay holdout may not be inspected to select features, transformations, windows, imputation rules, or thresholds.

Because the audited historical DraftKings candidate failed the frozen replay provenance requirements, this PIT freeze does not make that dataset eligible for governed historical replay. Unless another source passes the frozen audit, 2027 market validation remains prospective forward capture.

## Fail-closed leakage rule

Any feature row with unresolved future information, unverifiable dynamic-source availability, target-game contamination, or prohibited market information fails PIT eligibility.

No backfill may convert information learned later into information claimed to have been known earlier.

## Freeze boundary

Frozen here:
- the `available_at <= as_of` eligibility rule;
- feature-family leakage boundaries;
- market/model separation;
- lagging requirements;
- PIT-safe imputation requirement;
- provenance requirement;
- fail-closed behavior.

Not frozen here:
- exact feature formulas;
- rolling-window lengths;
- model coefficients;
- simulation/RNG semantics;
- calibration method;
- market quote-binding implementation;
- promotion thresholds.

Those remain separate queue work.
