# PREREGISTRATION — MLB F5 Distribution Challenger (Model Fix Lane, family 4)

- **Directive and owner constraints:** as PREREG_BATTER_PROPS
  header (challenger under preregistration; production FROZEN;
  M2/M4 verdicts precede adoption; candidacy requires beating the
  frozen engine AND both baselines, paired CIs entirely < 0).
- **Scope guard (inherited from Phase 2, unchanged):** this
  evaluation calibrates the F5 run **distributions only**. F5
  `eligible=false` and the deployment gate are untouched; no
  market readout is scored; no outcome speaks to deployment.
- **Label of any output:** RESEARCH_EVIDENCE — retrospective
  calibration evaluation. NOT a market verdict, NOT validation.
- **Written:** 2026-10-14, before any challenger score was
  computed on the test splits declared in §4.

## 1. The measured defect this challenger answers

Phase 2 (SPEC_F5; n = 2,400, every 2025 final): the production
build (team pools ≤ 30 games blended with the league prior at
strength 30 — "m30") does not beat climatology: total-runs CRPS
model 1.8206 vs climatology joint 1.8256 (paired Δ CI
[−0.0118, +0.0027], tie), joint log score worse (4.1637 vs
4.1283). Against its own unsmoothed build (strength 0) the m30
prior measurably helps (Δ CI [−0.0205, −0.0043]; support misses
140 → 2). Reading: the league prior is doing real work, the team
pools add ≈ 0.3% of CRPS (indistinguishable from zero), and the
prior's current strength is the only lever the evidence points
at. The challenger extends that single lever in the measured
direction: a stronger predeclared league prior on the identical
build.

## 2. Frozen evaluand (exact)

- `sportsedge/f5_distribution.py` `build_f5_distribution`
  (F5_DISTRIBUTION_VERSION `mlb_f5_empirical_state_v2_m30_league_prior`)
  at origin/main `2a713380c` (byte-identical to the Phase 2
  evaluand at `12999fc22`), production configuration
  `league_prior_strength = 30`.
- Features per `sportsedge/mlb_f5_features.py`: per team, F5
  runs-for / runs-against arrays over its most recent ≤ 30
  strictly-prior games (≥ 10 required); league prior = empirical
  F5 runs PMF over all completed regular-season team-halves in
  the prior 370 days (target date excluded), ≥ 200 halves.
  Evaluator assembles features by importing the production
  module's own parsing/scoring functions (Phase 2 §2(a)).

## 3. Challenger construction (the single changed constant)

- **Challenger = `build_f5_distribution` with
  `league_prior_strength = 90`** — 3× the production strength,
  predeclared, the extension of the m30 direction the Phase 2
  amendment and results identify. Nothing else changes: same
  features, same pools, same prior PMF, same builder code path
  (the builder accepts the strength as a parameter; using it is
  not a production edit).

## 4. Split discipline (declared before any run)

- **Design/diagnosis data:** 2025 (Phase 2's only F5 population).
  **Test data:** **2026 regular season (PRIMARY)** and **2024
  regular season (SECONDARY, corroborating)** — Phase 2 scored
  neither. This family's case is **TWO_SPLIT**, with the family
  verdict carried by the 2026 primary (§6) and the 2024 result
  reported in the same table; a contradiction between splits is
  reported as such, never averaged away.
- Populations transpose Phase 2 §4: regular-season games, both
  teams' pools satisfiable or the fixture is excluded and
  counted. For 2024, the sealed-window treatment of Phase 2
  §2(b) applies verbatim (halves from [2024-07-01, 2024-09-01)
  removed from the league prior; removal and halves counts
  reported). For 2026 no sealed window intersects (declared).
- Acquisition (transport only, before scoring): StatsAPI
  schedule + linescore chunks — for 2026, the season plus its
  370-day prior runway (the cache's coverage ends 2025-09-28;
  production's F5 schedule query carries no gameType filter, so
  chunks are acquired unfiltered, mirroring
  `acquire_statsapi_extra.py`); 2024 chunks are already cached.
  Fallback if 2026 acquisition fails: score the 2024 split alone
  and label the family SINGLE_SPLIT (2024); if both fail,
  FORWARD_ONLY filing as in PREREG_BATTER_PROPS §4.

## 5. Arms scored (identical fixture sets)

1. **FROZEN** — production m30 build (§2).
2. **CHALLENGER** — m90 build (§3).
3. **B1** — league climatology joint: both marginals = the
   fixture's own PIT league PMF, independence joint (Phase 2's
   definition).
4. **B2** — unsmoothed build (`league_prior_strength = 0`).

## 6. Metrics and gate

- Per fixture, from the built joint PMF (pre-readout): total-runs
  CRPS (**primary**), away/home marginal CRPS, joint log score
  (zero-mass states counted as SUPPORT_MISS, scored at the
  declared floor p = 1e-6; both reported), 3-class F5 moneyline
  Brier (descriptive).
- Paired per-fixture ΔCRPS with 95% CIs, block bootstrap over ISO
  weeks, 2,000 resamples, **seed 20261015**, per split and pooled
  within split only (splits are never pooled together).
- **Adoption gate (2026 primary):** ADOPT-CANDIDATE iff the
  challenger's ΔCRPS (total runs) CI is entirely < 0 against
  FROZEN **and** B1 **and** B2 on 2026. Otherwise KEEP FROZEN.
  The 2024 secondary is reported with the same comparisons; if
  2024 contradicts a 2026 pass, the recommendation is stated as
  SINGLE_SPLIT_PASS_CONTRADICTED and weighed accordingly —
  the gate itself does not move.

## 7. Verification required before scoring

- **Feature parity:** ≥ 25 sampled fixtures per split:
  evaluator-assembled features == `mlb_f5_features`-produced
  features on the same cached payloads (pool arrays elementwise;
  league PMF to 1e-12), with the §4 sealed-window removal as the
  single declared difference for 2024 (Phase 2 §6's rule).
- **PMF hygiene:** every built joint conserves mass to 1e-12;
  builder refusals on population fixtures counted with reasons.
- **Challenger identity check:** with strength set to 30 the
  challenger code path reproduces the frozen arm's PMFs exactly
  on samples (proving the only difference is the constant).
- **Determinism:** fixed seed; re-runs reproduce results except
  timestamps.

## 8. What the verdict does and does not do

As PREREG_BATTER_PROPS §8, plus the inherited scope guard: no
outcome here touches `eligible=false`, creates a market verdict,
or advances deployment. No re-tuning of the strength constant on
either test split is permitted; a second challenger needs a new
preregistration and a new untouched split.
