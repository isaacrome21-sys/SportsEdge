# MLB V8 P0 Temporal Audit Remediation — 2026-09-02

Independent audit identified two temporal-integrity defects in the V8 source merged at `e6586d5a534739618a7808744057f54ecaaff23f`.

## P0-1 — replay canonical target tolerance was symmetric

The replay verifier selected the closest canonical target with an absolute delta. That could qualify a provider snapshot occurring after the intended decision moment when it was still within the six-minute tolerance.

Remediation:
- canonical target matching is now one-sided;
- a snapshot must be at or before the target (`minutes_before_first_pitch >= target`);
- the six-minute tolerance applies only to earliness;
- a T-24.1 snapshot cannot qualify for the T-30 decision target;
- a T-36 snapshot may qualify for T-30;
- the manifest records `pit_target_tolerance_direction=EARLY_ONLY_AT_OR_BEFORE_TARGET`.

No existing replay manifest was present on the durable `data` branch when this remediation was prepared, so no prior replay qualification is grandfathered. Any future manifest must be rebuilt under the corrected rule.

## P0-2 — default Statcast cutoff used the UTC calendar date

Baseball Savant `game_date` is a game-local calendar date. Using `current.date()` after coercing `now` to UTC could allow the same U.S. game date after UTC midnight while games were still in progress.

Remediation:
- the default exclusive `game_date_lt` bound now derives from `America/Los_Angeles`, the latest regular MLB venue timezone;
- this fail-closes the current MLB calendar date across U.S. venues;
- explicit historical `end_date` remains deterministic and unchanged.

Boundary regression:
- `2026-09-03T00:30:00Z` resolves to `2026-09-02` in America/Los_Angeles;
- therefore the generated Statcast query uses `game_date_lt=2026-09-02`, not `2026-09-03`.

## Regression coverage

`tests/test_mlb_v8_temporal_guards.py` covers:
- T-36 accepted for T-30;
- T-24.1 rejected for T-30;
- UTC rollover boundary cannot advance the Statcast game-date cutoff;
- explicit Statcast historical end dates remain deterministic.

The dedicated `mlb-v8-contract` workflow now includes and executes these temporal guards.

## Governance

This remediation changes evidence qualification and temporal data hygiene only. It does not promote any MLB market, does not change the frozen forward-validation requirement, and does not make replay evidence sufficient for V8 promotion.
