# MLB Plate-Appearance Engine v1 — build + screen report (Oct 20, 2026)

Wave 2 of the build-all-engines program (owner directive, Oct 20
2026: any model that has no engine gets one built).  The three
per-batter first-plate-appearance forms — 1st PA Result, On Base
Yes/No, Grouped Result — terminated BLOCKED at
`PLATE_APPEARANCE_PBP_POOL_UNBUILT` (sportsedge/
mlb_plate_appearance_gates.py).  This build supplies the engine the
gate names.  **The gate itself is untouched**: its lift, and the
second blocker it names (`PLATE_APPEARANCE_SELECTION_SET_UNVERIFIED`
— DraftKings' exact selection lists / Grouped partition), are
separate owner-ruled steps.

## Construction — the proven M49 spec, implemented unchanged

Source of the specification (read before any code was written):

* `~/workspace/sportsedge/backtest_program_20261017/lanes/mlb/specs/
  SPEC_M49_PA.md` — SHA-256
  `2e2cb70d69607f9320dc9b6cd3b19e1fd71c98c4281515affe93e81eede3f84f`,
  recorded in that program's `specs/SPEC_HASHES.txt` before any M49
  score was computed (verified on disk at build time).
* Its evaluator `lanes/mlb/scripts/eval_m49_pa.py` and published
  results `lanes/mlb/results/mlb_m49_pa_results.json` (verdict
  BEATS_BASELINE at construction level).

The engine (`sportsedge/mlb_plate_appearance_engine.py`,
`ENGINE_ID = mlb_plate_appearance_engine_v1`) implements exactly
that construction:

* Six categories over the pool's `outcome_class` (spec partition,
  exhaustive): K / BB_HBP / SINGLE / XBH / HR / OTHER.
* PIT: pool game G feeds target T only if
  `G.game_completed_date < T.game_date`; same-season histories only.
* Eligibility gate: ≥ 50 strictly-prior same-season PAs, else a
  named refusal (`PLATE_APPEARANCE_INSUFFICIENT_PRIOR_PA`).
* Candidate: `p(c) = (count_b(c) + 50 · p_L(c)) / (n_b + 50)` —
  batter empirical shrunk toward the expanding league climatology,
  fixed k = 50 PAs.
* On Base: P(reached) with reached := {BB_HBP, SINGLE, XBH, HR},
  summed from the one priced joint distribution (no independence
  shortcut); OTHER thereby includes reach-on-error and fielder's
  choice, as the spec discloses.
* Grouped Result: the engine REFUSES it
  (`PLATE_APPEARANCE_GROUPED_PARTITION_UNVERIFIED`).  DK's exact
  3-way partition is not in the catalog evidence; inventing one
  would be fabrication.  Any verified partition is a deterministic
  coarsening of the priced distribution.

The spec's construction conditions on the batter's own history and
the league only.  The pool carries pitcher identity (so the opposing
starter's first-PA-faced history the gate's detail names is
derivable from the same pool), but the proven construction does not
use it and this engine adds no pitcher term — that would be a
substitute model.

Data: the stage-1 PBP pool (branch `research/mlb-pbp-pool-20261016`,
record in `research/mlb_pbp_pool/` there; builder sha256
`b766c51f…`).  Full artifacts live in workspace storage
(`~/workspace/sportsedge/mlb_pbp_pool_20261016/`) by that package's
design; the MANIFEST.json in workspace storage is byte-identical to
the branch's copy (sha256 `35e80206…`), and the 2025 pool file
hashes to the manifest pin (`699ac96a…`).  Consumed as a data
source; no pool data is committed here, and the pool branch is not
merged into this branch.

## Screen — run once, through the engine, on the sanctioned vintage

`screen_mlb_pa_engine.py` (this directory) replays the 2025 pool
with the spec's walk, taking every candidate distribution from the
engine's `shrunk_distribution`, and asserts the engine's indexed
pool path reproduces the walk counters on a deterministic sample
(64 spot checks, all passed).  Nothing was tuned: k and the gate
are the spec's, read from the engine module.

**Parity with the Oct 17 record: population counters exact**
(48,794 batter-games seen; 39,771 eligible; 152,053 PAs scored;
39,771 first PAs; ineligible-by-month identical), and every compared
figure — mean log losses, paired deltas, bootstrap CI endpoints —
matches with max abs diff **1.1e-16** (one binary mean; all others
0.0).  The engine is the construction, bit for bit.

Construction primary (all PAs, six-category, n = 152,053):
candidate 1.432046 vs league 1.442831 vs raw 1.448726;
Δ vs league **−0.01078 [−0.01231, −0.00918]**;
Δ vs raw **−0.01668 [−0.02272, −0.01176]** — BEATS_BASELINE,
reproducing the record.

### Per-family verdicts (screen labels)

| Family | n | Verdict |
|---|---|---|
| PLATE_APPEARANCE_RESULT | 39,771 first PAs | **CALIBRATED_CANDIDATE** |
| PLATE_APPEARANCE_ON_BASE | 39,771 first PAs | **DOES_NOT_BEAT_BASELINE** |
| PLATE_APPEARANCE_GROUPED_RESULT | — | **NO_DATA** |

* RESULT (six-category log score, 1st-PA subset): candidate 1.431560
  vs league 1.441634 vs raw 1.451125;
  Δ vs league **−0.01007 [−0.01248, −0.00740]**;
  Δ vs raw **−0.01956 [−0.02771, −0.01318]** — both CIs entirely
  below zero.
* ON_BASE (binary reached log score, 1st-PA subset): candidate
  0.618091 vs league 0.617801 vs raw 0.619539;
  Δ vs league **+0.00029 [−0.00048, +0.00106]** — the CI straddles
  zero and the point estimate favors the league; Δ vs raw
  −0.00145 [−0.00190, −0.00102].  The gate requires beating BOTH
  baselines, so the family records DOES_NOT_BEAT_BASELINE: the
  batter-level shrinkage that improves the full distribution and
  beats the batter's raw rate does not beat plain league
  climatology once collapsed to on-base yes/no on first PAs.
  Recorded as-is; the construction is unchanged.  (All-PA binary
  descriptive, as the record published it: candidate 0.624610 vs
  league 0.624749 vs raw 0.625937; Brier 0.216520 vs 0.216587.)
* GROUPED_RESULT: no score exists to report — DK's 3-way partition
  is unverified, and no partition was invented for this screen.

All CIs: paired per-PA log-score differences aggregated by ISO
week, block bootstrap 2,000 resamples, seed 20261017, per the spec.

## Tests

`tests/test_mlb_plate_appearance_engine_20261020.py` (18 tests):
hand-computed shrinkage pin; spec partition exactness; sufficiency
boundary at exactly 50 / 49 priors; not-in-pool and pool-unavailable
refusals; grouped-partition refusal; on-base equals the priced
distribution's reached mass; hostile PIT probes (future-game and
target-day injection bit-identical; same-date doubleheader never
feeds; a suspended game feeds only after its completion date);
identity ambiguity / unknown-name refusal; malformed-id/date
refusals; loader fail-closed on unmapped outcome, missing field,
bool id, bad PA number, bad date; pool game-metadata conflict
refusal; and an assertion that all three families still terminate
BLOCKED at the unchanged gate.

Run results (this branch): new tests + the M49 gate tests 35/35;
the MLB / batter / coverage slice 2,334 passed + 57 subtests, no
failures.

## Governance — what did not change

* No registration, eligibility, promotable, or validation field was
  touched anywhere.  The gates module has no engine-pointer field
  and was not edited; no config or registry file was edited.
* All three families remain BLOCKED on the canonical path at
  `PLATE_APPEARANCE_PBP_POOL_UNBUILT`, with
  `PLATE_APPEARANCE_SELECTION_SET_UNVERIFIED` still outstanding.
* What remains before any PA row can price: (1) owner-ruled gate
  lift now that a verified PIT pool + engine exist; (2) the
  selection-set verification (DK's exact selection lists and the
  Grouped 3-way partition) — catalog work; (3) a frozen forward
  test vs our own DK captures before any validation claim, per the
  standing harness rule.  Screen labels here are calibration
  evidence only: CALIBRATED_CANDIDATE is not validated, and PLAY
  remains unavailable.
