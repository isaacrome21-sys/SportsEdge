# PREREGISTRATION — CFB QB Passing Challenger (Model Fix Lane, family 5)

- **Directive and owner constraints:** as PREREG_BATTER_PROPS
  header (challenger under preregistration; production FROZEN;
  M2/M4 verdicts precede adoption; candidacy requires beating the
  frozen engine AND both baselines, paired CIs entirely < 0).
- **Governance scope (inherited from Phase 2, unchanged):** this
  evaluation covers the QB passing-yards family (matrix row C10)
  only. It does NOT spend CFB Attempt 1, does not touch the frozen
  four-family evaluation (C1–C3) or its population dispute, and
  does not register the family.
- **Label of any output:** RESEARCH_EVIDENCE — retrospective
  calibration evaluation of a research distribution. NOT a market
  verdict, NOT validation.
- **Written:** 2026-10-14, before any challenger score was
  computed on the test split declared in §4.

## 1. The measured defect this challenger answers

Phase 2 (SPEC_CFB_QB_PASSING): the production builder's chain
(team plays → pass share → QB attempt share → completions →
yards, components resampled jointly per prior game, no shrinkage,
no league prior) beats the QB's raw trailing empirical (2025
ΔCRPS CI [−0.794, −0.059]) but loses to the team-attempt chain
(B2) — 2025 model CRPS 46.88 vs B2 45.92 (CI [−0.081, +2.272],
not beaten); in the 2026 partial season the QB-specific links
significantly hurt (48.10 vs 44.09; CI [+2.804, +5.274]). The
program report's named candidate shape: **a team chain with a
shrunk QB adjustment**. The challenger is exactly that: the
team chain carrying the production builder's distribution at a
predeclared minority weight.

Also recorded, and deliberately NOT changed here: the identity
rule (plurality prior attempter over ALL prior games) excluded
59% of 2025 candidate team-games via ROLE_NOT_MATERIALIZED. That
rule is a CFB-lane design question (a window decision); changing
it in this lane would confound the challenger with a second
simultaneous change. It stays production's rule, the exclusion
rate on the test split is reported, and the population remains
"QB-stable teams" — stated, not hidden.

## 2. Frozen evaluand (exact)

- `sportsedge/research/cfb_qb_passing_distribution.py` at
  origin/main `2a713380c` (byte-identical to the Phase 2 evaluand
  at `12999fc22`), production seed policy and path count. The
  distribution is conditional ("QB starts with the role his PIT
  history shows"; declared p_starts = 0.90 rides on the object;
  the unconditional mixture is NOT_CONSTRUCTED and is not scored).

## 3. Challenger construction (every constant fixed here)

- **B2 team chain** exactly as Phase 2 §5: resample the team's
  prior games jointly on (team pass attempts, team
  yards-per-attempt), yards = PA × YPA_game, same path count and
  seed policy as the builder.
- **Challenger sample = a two-component mixture:** each path is
  drawn from the production builder's path sample with
  probability **γ = 0.25** and from the B2 path sample with
  probability 0.75, at the builder's production total path count,
  under a seed policy fixed in the evaluator and recorded in the
  results file. CRPS and threshold shares are computed from the
  pooled mixture sample. γ = 0.25 is predeclared (the QB chain is
  retained as a minority adjustment, per the §1 evidence) and is
  the ONLY value scored: **no γ-sensitivity sweep on the test
  split is permitted** — sweeping γ would be tuning on test data.

## 4. Split discipline (declared before any run)

- **Design/diagnosis data:** 2025 primary + 2026 partial
  (Phase 2). **Test data:** the **2024 season** (fixtures
  Aug–Dec 2024) — Phase 2 used 2024 games only as prior history
  for 2025 fixtures; no 2024 fixture was scored, binned, or
  inspected. This family's case is **SINGLE_SPLIT (2024)**.
- Population transposes Phase 2 §2(a)/§4 to 2024: FBS games;
  candidate fixture = (team, game) where the QB identity is
  established from strictly prior data (plurality pass-attempter
  over his prior games), the QB has ≥ 5 usable prior games at
  as_of = kickoff − 3h, and the role materialized (QB attempted
  ≥ 60% of team pass attempts in the fixture). Illinois fixtures
  excluded (standing rule). Bowls/playoff games in Dec 2024 are
  regular population (declared, as Phase 2 declared for 2025).
- Exclusions counted: INSUFFICIENT_PIT_HISTORY,
  ROLE_NOT_MATERIALIZED, IDENTITY_NOT_ESTABLISHED,
  ILLINOIS_EXCLUDED, BUILDER_REFUSAL (with reason).
- Assembly: prior-game records from sportsdataverse/cfbfastR
  public game-stats files, seasons 2022–2024 (2022–2023 files are
  history runway for early-2024 fixtures; the builder's PIT
  filters govern what enters any fixture). FBS set for 2024
  derived from NCAA.com's official standings by the Phase 2
  method (`derive_fbs_teams.py`), derived fresh for 2024 and
  recorded — not assumed. Acquisition is transport only, before
  scoring. Fallback if assembly proves impossible: FORWARD_ONLY
  filing, as in PREREG_BATTER_PROPS §4.

## 5. Arms scored (identical fixture set)

1. **FROZEN** — production builder (§2).
2. **CHALLENGER** — §3 mixture.
3. **B1** — QB trailing empirical distribution (Phase 2's
   definition).
4. **B2** — team-attempt chain (§3) — note CHALLENGER vs B2
   isolates the retained 25% QB adjustment.

## 6. Metrics and gate

- **Primary: CRPS** from each arm's path sample / empirical CDF,
  computed exactly as Phase 2 computed it (method restated in
  the results file).
- **Calibration (descriptive):** p5–p95 empirical coverage
  (nominal 0.90), PIT-histogram summary.
- **Secondary (descriptive):** threshold Brier at ladder
  thresholds 150 / 200 / 250 / 300 for all arms.
- Paired per-fixture ΔCRPS with 95% CIs, block bootstrap over ISO
  weeks, 2,000 resamples, **seed 20261015**.
- **Adoption gate:** ADOPT-CANDIDATE iff the challenger's ΔCRPS
  CI is entirely < 0 against FROZEN **and** B1 **and** B2.
  Otherwise KEEP FROZEN.

## 7. Verification required before scoring

- **Worked-example reproduction:** the evaluator reproduces the
  CFB lane's published Collins distribution from its preserved
  evidence records (mean 174.4, sd 91.2, exceedance shares 150+
  0.583 / 200+ 0.414 / 250+ 0.235 / 300+ 0.091; ±0.01 shares,
  ±1.5 yards) under the production seed — Phase 2 §6 verbatim.
  Failure stops the run.
- **Assembly audit:** 10-fixture sample from the 2024 assembly
  cross-checked against ESPN game summaries (QB att/comp/yards;
  team pass/rush attempts); exact agreement on ≥ 9/10 required,
  else assembly switches to ESPN summaries for the whole
  population and the switch is recorded (Phase 2 §2(b) rule).
- **Leakage tripwire:** ≥ 10 fixtures, as Phase 2 §6 (appended
  fixture game changes the distribution; scored build
  bit-identical when a post-as-of game is added).
- **Determinism:** fixed seeds; re-runs reproduce results except
  timestamps.

## 8. What the verdict does and does not do

As PREREG_BATTER_PROPS §8: the family stays UNREGISTERED and
UNVALIDATED regardless of outcome; an ADOPT-CANDIDATE is a
recommendation to Isaac only. No re-tuning of γ on the 2024
split is permitted; a second challenger needs a new
preregistration and a new untouched split.
