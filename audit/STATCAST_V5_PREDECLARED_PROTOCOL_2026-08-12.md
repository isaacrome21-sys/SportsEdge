# SportsEdge MLB Statcast-required V5 protocol — 2026-08-12

## Purpose

The user requires Statcast to be an actual predictive input, not presentation context. Existing GAME_SCORE_V4_CUTOFF_CORRECT and NRFI_V4_CUTOFF_CORRECT remain valid historical artifacts for their prior validation claims, but they are not Statcast models and may not be represented as such.

## Frozen chronology

- Training: 2021-2023 regular-season data.
- Calibration/model-selection: 2024 only.
- Final untouched historical holdout: 2025 only.
- 2026 labels are prohibited from model fitting or threshold tuning. 2026 may be used only as post-hoc/forward-shadow evidence after the historical gate is frozen.
- For every prediction row, all game outcomes and Statcast events must have event dates/timestamps strictly before the target game's cutoff. Same-day completed games may not update another same-date game's features.

## Permitted sources

- Official MLB StatsAPI for schedule, identity, results, probable pitchers, lineups/rosters and non-Statcast game facts.
- Official MLB Baseball Savant / Statcast for contact-quality and expected-stat inputs.
- Sportsbook data is price-only and is prohibited from Model_P features, calibration targets, feature imputation, or model selection.

## Required GAME_SCORE_V5_STATCAST feature family

The new game scoring model must consume the legacy sportsbook-independent history/context feature family plus, at minimum:

- off_xwoba
- off_xba
- off_barrel_rate
- off_hard_hit_rate
- off_avg_exit_velocity
- opp_sp_xwoba_allowed
- opp_sp_xba_allowed
- opp_sp_barrel_rate_allowed
- opp_sp_hard_hit_rate_allowed
- opp_sp_avg_exit_velocity_allowed

The contact-quality metrics must be reproducible from official Savant event fields (estimated_woba_using_speedangle, estimated_ba_using_speedangle, launch_speed, launch_speed_angle; launch_speed_angle=6 is a Barrel; hard-hit is launch_speed >= 95 mph). These fields must appear in the serialized artifact's actual run_features array and the artifact must declare SPORTSEDGE_STATCAST_V1 and statcast_consumed_by_model=true. Metadata declaration without actual model-column membership is a hard failure.

## Required NRFI_V5_STATCAST feature family

The first-inning model must consume the legacy first-inning history/context feature family plus, at minimum:

- away_top_order_xwoba
- home_top_order_xwoba
- away_top_order_barrel_rate
- home_top_order_barrel_rate
- away_sp_xwoba_allowed
- home_sp_xwoba_allowed
- away_sp_hard_hit_rate_allowed
- home_sp_hard_hit_rate_allowed

Top-order values must be derived from the resolved projected/confirmed batting order and prior-only Statcast records. Missing lineup identity or missing required Statcast evidence blocks the candidate; no league-average substitution is permitted in production scoring unless a separately predeclared missingness model is validated.

## HITS / TOTAL_BASES direction

Future Statcast-aware hitter artifacts must explicitly consume batter xwOBA, xBA, barrel rate, hard-hit rate and average exit velocity plus opposing-starter allowed contact quality. Existing HITS/TOTAL_BASES artifacts are not relabeled or self-promoted by this protocol.

## Fail-closed rules

1. A legacy artifact without the Statcast contract cannot emit a new official Model_P on the Statcast-required runtime.
2. A claimed Statcast artifact whose actual model feature contract omits any required Statcast feature is rejected.
3. Missing/non-numeric required Statcast live inputs block scoring.
4. Statcast fetch failure, cutoff ambiguity, player/team binding ambiguity, or probable-starter ambiguity blocks scoring.
5. Sportsbook price/probability contamination remains prohibited.
6. No deployment eligibility change is allowed until the new V5 artifacts independently pass historical holdout, live feature parity, runtime attestation and Truth Gate tests.

## Acceptance evidence required before deployment

- Exact source-range/cutoff tests for every historical Statcast row.
- Feature-contract tests proving the model matrix contains the required Statcast columns.
- 2025 untouched holdout results under frozen tolerances declared before scoring.
- Exact artifact SHA-256 hashes.
- Live-slate attestation showing required Statcast values were fetched, bound, cut off correctly and consumed by the same model contract.
- Explicit failure tests proving legacy V4, missing Statcast, malformed Statcast and sportsbook-contaminated features cannot produce official probabilities.

Until those gates pass, the correct production state under the Statcast-required policy is BLOCKED rather than silently falling back to V4.
