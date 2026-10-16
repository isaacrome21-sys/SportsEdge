# PREREGISTRATION — MLB First-Inning Challenger (Model Fix Lane, family 3)

- **Directive and owner constraints:** as PREREG_BATTER_PROPS
  header (challenger under preregistration; production FROZEN;
  M2/M4 verdicts precede adoption; candidacy requires beating the
  frozen engine AND both baselines, paired CIs entirely < 0).
- **Label of any output:** RESEARCH_EVIDENCE — retrospective
  calibration evaluation. NOT a market verdict, NOT validation.
- **Written:** 2026-10-14, before any challenger score was
  computed on the test split declared in §4.

## 1. The measured defect this challenger answers

Phase 2 (SPEC_FIRST_INNING): the production binary model
(`price_first_inning_binary`, per-half p = ½·Jeffreys(team scoring
rate) + ½·Jeffreys(starter allowed rate)) beats team-only
information decisively (2025 ΔBrier CI [−0.0096, −0.0046]) but adds
nothing over league climatology (2025: model Brier 0.2495 vs
climatology 0.2503, Δ CI [−0.0036, +0.0020]; 2024 the same shape).
The Poisson counts sibling is far worse (0.2693/0.2764) — the
binary construction is confirmed and is NOT revisited. The honest
description of the frozen model is "climatology plus an unshrunk
team/starter tilt whose measured value is indistinguishable from
zero." The challenger is exactly that sentence, built: the binary
construction with both component rates shrunk toward the league
rate by a predeclared amount.

## 2. Frozen evaluand (exact)

- `sportsedge/mlb_first_inning_model.py` `price_first_inning_binary`
  (FIRST_INNING_BINARY_VERSION
  `mlb_first_inning_binary_starter_jeffreys_v1`) at origin/main
  `2a713380c` (byte-identical to the Phase 2 evaluand at
  `12999fc22`).
- Pools per `sportsedge/mlb_first_inning_data.py`: team pools =
  strictly-prior games in the same venue role (≤ 30, ≥ 10
  required); starter pools = the actual starter's strictly-prior
  starts (≤ 15, ≥ 5 required). A fixture whose four pools are not
  all satisfiable is excluded and counted. Actual starters from
  pitching gameLogs (gamesStarted == 1), as Phase 2 §2(a).

## 3. Challenger construction (every constant fixed here)

For each half-inning component, the production Jeffreys rate is
r = (x + 0.5) / (n + 1) over its pool (x = indicator count,
n = pool size). The challenger replaces each component rate with

  **r′ = (x + 0.5 + A · r_L) / (n + 1 + A), with A = 20
  games-equivalent,**

where r_L is the expanding league rate of the same indicator over
strictly-prior dates in the test season (team component: league
first-inning team scoring rate; starter component: league
first-inning runs-allowed rate per start — computed from the same
cached linescore corpus, strictly prior, with the exact
definitions restated in the results file). Everything else is
production's: p_half = ½·r′_team + ½·r′_starter, and
P(YRFI) = 1 − (1 − p_away)(1 − p_home).

## 4. Split discipline (declared before any run)

- **Design/diagnosis data:** 2025 primary + 2024 secondary
  (Phase 2). **Test data:** the **2026 regular season** —
  untouched by Phase 2. This family's case is **SINGLE_SPLIT
  (2026)**.
- Population transposes Phase 2 §4 to 2026: regular-season games,
  both starters identified, all four pools satisfiable; exclusions
  counted (STARTER_UNIDENTIFIED, POOL_*_INSUFFICIENT). Sealed
  window not applicable to 2026 (declared); any pool runway
  reaching into 2025 uses cached payloads as transport only —
  pools follow the production data module's own semantics,
  enforced by the §6 parity check.
- Acquisition (transport only, before scoring): StatsAPI
  schedule + linescore chunks covering the 2026 season and its
  pool runway, and pitching gameLogs 2026, into the program disk
  cache. Fallback if acquisition fails: FORWARD_ONLY filing, as
  in PREREG_BATTER_PROPS §4.

## 5. Arms scored (identical fixture set)

1. **FROZEN** — production binary model (§2).
2. **CHALLENGER** — §3.
3. **B1** — league climatology: expanding season-to-date YRFI
   rate as a constant probability (Phase 2's definition).
4. **B2** — team-only Jeffreys binary (starter term removed;
   Phase 2's definition).

The Phase 2 secondary (Poisson counts) model is NOT re-armed and
no challenger is built on it — the binary construction is the
confirmed one; the Poisson arm's recorded failure stands.

## 6. Metrics and gate

- Brier and log loss per fixture (predicted P(YRFI) vs realized
  indicator), pooled over the 2026 population; calibration by
  decile descriptive.
- Paired differences with 95% CIs, block bootstrap over ISO
  weeks, 2,000 resamples, **seed 20261015**.
- **Adoption gate:** ADOPT-CANDIDATE iff the challenger's ΔBrier
  CI **and** ΔLogLoss CI are entirely < 0 against FROZEN **and**
  B1 **and** B2. Otherwise KEEP FROZEN. (Declared expectation, so
  the result is read honestly either way: the hard leg is B1 —
  Phase 2's unshrunk tilt was worth ΔBrier ≈ −0.0008 ± 0.0028
  against climatology, so a shrunk tilt may again tie B1; a tie
  is KEEP FROZEN under this gate, and it would confirm the family
  is a climatology model with a decorative tilt.)

## 7. Verification required before scoring

- **Parity:** ≥ 25 sampled fixtures: evaluator pools ==
  `mlb_first_inning_data.prior_pools` /
  `starter_first_inning_allowed` outputs on the same cached
  payloads (25/25), mirroring Phase 2 §6.
- **Spot integrity:** ≥ 10 fixtures: realized first-inning runs
  from cached linescores match `parse_completed_linescore_game`'s
  first-inning fields (Phase 2 §6).
- **Challenger unit checks:** with A = 0 the challenger reduces
  exactly to the frozen model (verified on samples, not scored);
  r′ ∈ [0, 1] for all components.
- **Determinism:** fixed seed; re-runs reproduce results except
  timestamps.

## 8. What the verdict does and does not do

As PREREG_BATTER_PROPS §8. Additionally: the family's card state
(priced-research, unvalidated) is unchanged by any outcome here,
and no re-tuning of A on the 2026 split is permitted.
