# Football Key-Number Baseline Specification

Integration state: `INTEGRATION_UNRUN`.

Design only. No football simulator code is changed by this document.

## Current-state finding

`main:sportsedge/core/simulate/football.py` currently uses `KeyNumberMarginModel` with explicit empirical point masses and `JointScoreSimulator` samples from that margin PMF. `main:sportsedge/sports/nfl/simulator_profile.py` builds `empirical_key_mass` at signed margins `-7, -3, 3, 7` from a real-history audit.

That is a valid legacy score-level approach, but it is **not** the target architecture for the event-rich simulator.

## Target rule

Do **not** inject probability mass at margins 3 or 7 into the event-rich production generator.

The generative path must create score shapes from football events and rules:

- possessions / drives or plays,
- touchdowns,
- field goals,
- extra points,
- two-point attempts,
- safeties where modeled,
- fourth-down decisions,
- end-of-half/end-of-game clock dynamics,
- overtime rules where applicable.

ML, spread, total, team total, winning margin, and derivative markets are read-outs from the same simulated paths. There is no separate key-number model and no read-out fudge factor.

If the resulting score-margin distribution misses empirical mass around 3 or 7, that is **simulator misspecification**. The repair belongs in the football event dynamics, not in a post-generation point-mass injection.

## Historical validation window

For this 2026 research cycle, freeze the baseline to the most recent five completed NFL seasons:

`[2021, 2022, 2023, 2024, 2025]`

The artifact must record the exact seasons. Do not use a timeless constant because NFL margin frequencies can shift with rule changes, overtime rules, fourth-down behavior, kicking accuracy, and two-point decisions.

## Baseline outputs

From regular-season games in the frozen window, report at minimum:

- total scored games,
- signed margin frequency at `-7, -3, 3, 7`,
- absolute margin frequency at `3, 7`,
- per-season frequencies,
- source identity/hash,
- any excluded/missing-score games.

## Validation test

Generate a large frozen sample from the event-rich simulator with a fixed seed/config and compare simulated vs historical key-number frequencies.

The acceptance tolerance must be **declared before seeing the simulated comparison**. It may be expressed from historical and simulation sampling uncertainty, but it cannot be widened after observing a miss.

A failure does not authorize injecting mass. Diagnose event dynamics instead: drive ending rates, FG/TD mix, XP/2PT behavior, clock/late-game strategy, overtime, or other structural causes.

## Determinism

The event-rich simulator must require a stable seed identity for acceptance fixtures. The current legacy `JointScoreSimulator(seed=None)` behavior is not sufficient for byte-identical replay when callers omit a seed.

## Three statuses

- PRESENT ON MAIN: **NO — this target spec is on the research/docs branch; legacy key-mass code remains on main**
- RUNTIME EXECUTED: **NO — no event-rich key-number validation run exists**
- PRODUCING EVIDENCE: **NO**

The current real-history audit/profile code on main is source infrastructure, not evidence that the future event-rich generator reproduces key numbers without injection.
