# PGA H2H Amendment 1 — ADOPTION RECORD

**Date:** 2026-10-30 · **Act:** owner-delegated adoption · **Status after
this record:** Amendment 1 to the PGA H2H design **ADOPTED**; the three
unpinned §4 constants **SETTLED** (below); the design itself remains
**NOT FROZEN**; the G-PGA-2 content pin remains **NOT ADMITTED**; the
Leg 1 screen remains **NOT_EXECUTABLE** (the executor's pin gate still
refuses). Family state: `PGA / TOURNAMENT_MATCHUPS_72H` — DESIGN ONLY.
All staking language is PAPER / research only.

## The delegation

On Oct 30, 2026 (~17:33 CT), Isaac answered Rocky's prepared
two-decision packet (CBB Amendment 2 adoption; PGA Amendment 1
adoption) with **"Whatever you suggest."** That answer delegates these
decisions; Rocky ruled **ADOPT** on both, and this record is the PGA
decision and its reasons — the same delegation pattern as the Oct 29,
2026 de-vig ruling and the Oct 28, 2026 Lane A adoption
(`research/lane_a_recalibration_20261028/ADOPTION_RECORD.md`). Isaac
can reverse any part of it with a word, and reversal is a new record,
not an edit of this one.

## The decision

### 1. Amendment 1 is adopted as written

Amendment 1 (PR #2896, branch head `7f3c5447ae7b501bed898768c745c52bbf59a3c8`,
merged to main as a draft record at `8ce7faa2f7754261d0cb100088c01293233e4c26`)
is adopted in full. Design §6's clause "(b) an OWGR-points-implied
reference rating" is replaced by the OWGR-rank-implied Bradley–Terry
reference (b′) exactly as Amendment 1 §3.2 defines it: strength
`s(i) = r_i^(−α)` from the per-event `owgr_rank` field on the pinned
DataGolf pages, validity = integer ≥ 1 (the corpus's only invalid
values are the −9999/−9998 sentinels), pairwise form
`P(i ahead of j) = r_j^α / (r_i^α + r_j^α)`, and the single scale α
estimated by maximum likelihood strictly on §6's own fit windows
(golden-section search on the concave objective, bracket < 1e-6).
`dg_pts` stays disqualified (it is an outcome field — lookahead, per
the amendment's §3.1 measurement) and `dg_rank` stays unused.

**The zero-parameter variant is expressly NOT adopted.** Amendment 1
§3.3 names fixing α = 0.5 a priori as a separate owner decision; it is
not taken. The fitted-α definition governs.

Nothing else in the design changes — reference (a), the pass bar
(pooled H2H log loss strictly better than BOTH references; calibration
error ≤ 0.05; ≥ 1,500 test matchups per season), the fit/test
chronology (≤2022→2023, ≤2023→2024, ≤2024→2025), §4's construction
form, §5's point-in-time rules, Leg 2, and §7's multiplicity policy all
stand word-for-word as designed. This adoption alters no criterion.

### 2. The three unpinned §4 constants are settled

The executor's `READINGS_REGISTER.md`
(`research/pga_h2h_executor_20261028/`) flags three design parameters
as UNPINNED, with the verdict path refusing while any is unset. They
are settled here, under the same delegation, so the later freeze act
incorporates them verbatim (any change after this record is a new
decision, recorded the same way):

| Parameter | Settled value | Basis (one line) |
|---|---|---|
| `shrinkage_prior_rounds` (§4.1) | **20** (weighted rounds) | Empirical-Bayes ratio σ²/τ² = 21.1 measured on the pinned corpus's priced population (§A below); 20 adopted at the estimate |
| `cut_size` (§4.4) | **65** | The PGA Tour's standard cut — top 65 and ties — in force for all three test seasons; the register's own named standard |
| `day_draw_sd` (§4.3) | **0.70** strokes | Split-half covariance estimate 0.699 of the shared course-day component on the pinned corpus (§A below); the conservative of two estimators |

Reasoning, per constant:

- **Shrinkage = 20.** In the executor's form
  `skill = (Σ w·sg + k·field_mean) / (Σ w + k)`, the empirical-Bayes
  constant is k = σ²/τ², the ratio of within-player round-SG variance
  to true between-player skill variance. Measured on the pinned
  corpus over exactly the population the executor prices (players
  with ≥ 40 measured rounds — the design's UNPRICED floor): σ² = 7.72
  (round-SG SD 2.78), τ² = 0.365 (skill SD 0.60), k = 21.1. Adopting
  20: a typical Tour regular's decayed weight over the trailing 24
  months is Σw ≈ 25–35, so his measured mean is shrunk roughly 40%
  toward the field mean; a minimum-sample player (Σw ≈ 15–20) is
  shrunk about half; a full-data elite keeps the majority of his
  measured edge. That is a meaningful pull that does not swamp signal.
  (Sensitivity, disclosed: over all players with ≥ 10 rounds the same
  ratio is 10.4 — that population's wider skill spread is not the
  priced population, so it does not govern.)
- **Cut size = 65.** The PGA Tour cut rule throughout the fit and
  test seasons is top 65 and ties after round 2; §4.4's "the
  simulated cut" reads on that rule, and the executor's R-SIM-1
  already implements the ties half (ties at the line survive).
  Disclosed limit: a minority of corpus events run different or no
  cuts (the majors at 50/60/70, limited-field no-cut events). The
  design prescribes one simulated-cut constant for the construction;
  65 is the Tour rule for the modal event and no per-event cut table
  is introduced by this act.
- **Day-draw SD = 0.70.** §4.3's shared course-day draw is the
  round-level condition component common to the whole field (weather,
  setup). Measured on the pinned corpus from R1/R2 field-mean
  score-to-par deviations (full fields both rounds; R3/R4 excluded —
  cut survivors bias the field mean): the noise-free split-half
  covariance estimator gives Var = 0.489 → SD 0.699; the direct
  field-mean estimator, corrected for field-mean sampling noise,
  gives 0.78–0.80. Adopted: **0.70**, the split-half value — the
  estimator that cannot be inflated by sampling noise or field
  composition. In the simulation this makes the same-round pairwise
  correlation ≈ 0.49 / (7.72 + 0.49) ≈ 6%, a real but modest shared
  component.

### 3. The readings register is confirmed

The ten named readings in `READINGS_REGISTER.md` (R-OUT-1, R-SKILL-1…3,
R-COURSE-1, R-VAR-1…2, R-SIM-1, R-REFA-1, R-CAL-1, R-SET-1) are
confirmed as the operative readings, unchanged — each is the most
direct reading of the design text, chosen before any result existed.
The freeze act re-affirms them verbatim. The register's fourth
unpinned item, `seed`, stays what the register says it is: run-record
material, required explicitly at any verdict run; it is not pinned
here.

## What this act does NOT do

- **It does not freeze the design.** Freezing remains a separate
  owner act under the design's header. No clock starts; nothing
  counts.
- **It does not admit the G-PGA-2 content pin.** The pin packet
  (PR #2917, merged `a2cca537df13efff83e2ce7ad29d55871c998bd0`) stands
  as prepared; its manifest still reads `DRAFT — NOT ADMITTED`.
  Admission is a separate governed act, which must also re-verify one
  rank point-in-time spot check per Amendment 1 §4.
- **It runs no screen.** The executor (`PGA_H2H_EXECUTOR_V1`, PR
  #2918, merged `aed769f75ae2488aee79f03ebef37a1fd984fd73`) still
  refuses any verdict run: `CONTENT_PIN_NOT_ADMITTED` stands. The
  `AMENDMENT_1_NOT_ADOPTED` refusal ground is the only one this act
  retires — a future governed run attests `amendment_adopted` against
  this record.
- **It touches nothing else.** The amendment draft file, the design
  file, the executor, the readings register, and the admission packet
  are all byte-untouched by this PR; this record governs by reference.
  No threshold anywhere in the program moves.

## Appendix A — measurement of record for the settled constants

Measured 2026-10-30 by Rocky over the extracted content of the pinned
corpus (the G-PGA-2 packet's store: 157 events, 19,630 rows, corpus
sha256 `cef59544a3f9f813db90154eed0715ccd2d4cd09acb486dbe12ae7585eec96d6`;
extraction `PGA_DG_CONTENT_EXTRACT_V1`). These are parameter
derivations from design data, not screen results — no fit, simulation,
or scoring was run.

- **Shrinkage inputs:** 1,259 players with ≥ 1 SG round; priced
  population (≥ 40 measured rounds) = 334 players. Pooled
  within-player round-SG variance (own-mean centered) σ² = 7.7217;
  variance of player means 0.4357; mean sampling-noise variance
  0.0704; τ² = 0.3653; k = 7.7217 / 0.3653 = 21.14. All-players
  (≥ 10 rounds) sensitivity: σ² = 7.7862, τ² = 0.7494, k = 10.39.
- **Day-draw inputs:** 157 events, 314 R1/R2 event-rounds. Raw
  field-mean deviation SD 0.578 (Var 0.334); single-course-only subset
  (154 events; the 3 multi-course-par AT&T Pebble Beach Pro-Am
  editions excluded) Var 0.339 — the estimate is not a multi-course
  artifact. Split-half estimator (random halves of each round's
  field, seed 20261030): Cov(dA, dB) = 0.2443 → Var(day) = 2·Cov =
  0.4887 → SD 0.6990. Direct estimator with sampling-noise correction
  (Var ε ≈ 0.033–0.073 depending on the score-SD input): SD 0.78–0.80.

## Verification (this PR)

- Freeze-coverage: the single touched path
  (`research/new_sports_designs_20261027/PGA_H2H_AMENDMENT_1_ADOPTION_RECORD.md`)
  checked against `config/freeze_reconciliation_registry_v1.json`
  with the repo matcher
  (`scripts/reconcile_freeze_deltas.py::_covered_change`, all 11
  bundles): **not covered** — this act cannot poison a frozen family.
- PR-only gates: pyproject `dependency-groups.dev` set equals
  `requirements-test.txt` exactly (11 = 11) on the base; this PR
  touches no code, so the ruff gate (E9,F821,F822,F823,F811) has no
  surface.
- Executor refusal state re-verified on the base head: the verdict
  path refuses on `AMENDMENT_1_NOT_ADOPTED` +
  `CONTENT_PIN_NOT_ADMITTED` with the draft manifest
  (`landing_check_result.json`); after this act the first ground is
  retired by attestation against this record and the second stands.
