# NFL Hybrid Context

SportsEdge uses a PIT-provenance sidecar for objective NFL context that is immediately usable by manual/hybrid review but is not a predictive Model_P or Truth Gate input until separately validated.

## Modes

- `AUTO`: approved objective providers only. Missing values remain explicit `MISSING`/`MISSING_PROVIDER`.
- `MANUAL`: human-entered objective observations. Every observation requires `source_type=MANUAL`, operator ID, timestamp, source URI/hash, and optional justification.
- `HYBRID`: AUTO base plus MANUAL class-level overrides/fills with an audit record preserving the replaced AUTO source hash and the MANUAL source hash.

## Objective context classes

Venue/surface, weather, rest/travel, injury/availability, snap/usage/workload, personnel/packages, defensive matchup/coverage, special teams, coaching tendencies, and workload/leash.

## Governance

The sidecar is always `model_p_eligible=false` and `truth_gate_eligible=false` at introduction. Social picks, handicapper picks, public betting, ticket/handle percentages, sportsbook prices, market probabilities, and closing-line data are prohibited from the context payload.

Missing data is never inferred or silently zero-filled. Objective context is collected and archived first; individual features may be promoted into Model_P only after PIT history and shadow validation demonstrate lift for the relevant market family.

## Objective provider wiring

The first provider layer is implemented in `sportsedge/sports/nfl/context_providers.py`.

- Weather/roof: versioned stadium records, NWS hourly snapshots, kickoff-hour selection, field-relative wind rotation, fixed-roof closure, and fail-closed retractable-roof decisions.
- Injury/availability: official-source-only status and practice history with PIT timestamp enforcement. IR/PUP and ramp fields remain source-derived rather than media-inferred.
- Rest/travel: deterministic schedule-derived rest, short-week, post-bye, travel distance, timezone shift, consecutive road, neutral/international, and body-clock fields.
- Workload/leash: L3/L5 snap summaries, routes/targets/carries/pass-attempt/pass-rush medians, snap-share trend, injury-ramp and short-week state, and an explicit projected snap band that remains non-Model_P.

## RUN IT path

1. AUTO attempts every context class.
2. Missing providers and values stay explicit.
3. Optional MANUAL observations require operator provenance.
4. HYBRID merges AUTO base + MANUAL overrides/fills while retaining both source hashes in the audit log.
5. The merged sidecar attaches to the game/slate object for RUN IT.
6. Model_P and Truth Gate remain unchanged until PIT history and shadow validation justify selective feature promotion.

Public/social market context remains a separate context stream and is never merged into this sidecar.
