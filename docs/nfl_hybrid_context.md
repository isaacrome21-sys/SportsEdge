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

RUN IT should default to HYBRID when both AUTO providers and manual objective overrides are available. Public/social market context remains a separate context stream and is never merged into this sidecar.
