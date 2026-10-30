# AMENDMENT to PREREG_F5 — strength-90 mechanism correction

- **Filed:** 2026-10-14 (America/Chicago), BEFORE any F5 challenger
  score was computed. Base prereg
  (SHA-256 378a60071ba12895288bf419208855f3f319b3e397e0c48321257f81a824155c)
  unchanged except for the mechanism sentence below; no constant
  changes, no new baselines, no gate changes.

## The defect in the base prereg's §3 premise

PREREG_F5 §3 states: "(the builder accepts the strength as a parameter;
using it is not a production edit)." Verified FALSE at the frozen
evaluand `sportsedge/f5_distribution.py` (SHA-256
031b2e7b60236232999fb0b59dd0b499e17526f8d8d0b6271ddd2367dbd3fbd8 —
byte-identical between origin/main 2a713380c and the Phase 2 evaluand
12999fc22):

1. `build_f5_distribution(features, league_prior_strength=...)` rejects
   any strength not in `{0, LEAGUE_PRIOR_STRENGTH}` (module global = 30)
   with `F5DistributionError("unsupported league prior strength")`.
   Strength 90 raises.
2. `_smoothed_pmf` reads the module-global `LEAGUE_PRIOR_STRENGTH`
   (30), not the call parameter — so the parameter does not control the
   smoothing weight at all.

## Amended construction (mathematical definition UNCHANGED)

The challenger remains: the identical `build_f5_distribution` code
path, same features, same league PMF, with the league-prior strength
= 90, i.e. marginals (counts + 90·league) / (n + 90). The
evaluator-side mechanism is:

1. Copy the feature dict with `league_prior_strength = 90`.
2. In the evaluator process only, temporarily rebind the module global
   `sportsedge.f5_distribution.LEAGUE_PRIOR_STRENGTH` to 90.
3. Call the production `build_f5_distribution(..., league_prior_strength=90)`.
4. Restore the module global in a `finally` block.

No repo file is touched; production stays FROZEN. The §7 strength-30
identity check is preserved and meaningful under this mechanism: the
same parameterized challenger path with strength=30 must reproduce
the frozen arm's PMFs exactly on samples (proving the only difference
is the constant).

## Label caveat (recorded, not hidden)

The builder's `F5_DISTRIBUTION_VERSION` constant still reads
`mlb_f5_empirical_state_v2_m30_league_prior` inside the challenger's
returned distribution, because the version string is a separate
constant from the strength. The results file records the challenger's
actual strength (90) explicitly alongside every arm.
