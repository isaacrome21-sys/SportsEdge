# MLB Retrospective Market-Leg Lane — Stage 2 Report

**Stage 2 of the lane (owner order): M6, M3, M29, M31, N1–N3.**
Stage 1 (M2 + M4, both DOES_NOT_BEAT_MARKET) is reported in
`REPORT.md` and published on the research branch.

**Label: RESEARCH_EVIDENCE — retrospective, development data.**
Every verdict in this report is a calibration verdict against a
naive baseline (no market leg exists historically for any of these
families; each item states its forward-only market status). Nothing
here satisfies the PR #2077 strict paired contract, promotes any
family, or changes any model, registry entry, or threshold.
Validated families remain **zero**; PLAY remains unavailable.

## 0. Provenance — how to reproduce every verdict

- **Research branch:** `research/mlb-market-legs-20261014` on
  `isaacrome21-sys/SportsEdge`, held unmerged — publication for
  reproduction, not a merge candidate.
- **Housekeeping from Stage 1 — closed.** The supplementary
  `VERDICTS_M2_M4.md` (local commit `4d5e8b89d`, whose pushes
  stalled twice on confirmation timeouts in Stage 1) rode this
  stage's first push and **landed**: remote branch head
  `bec4aee43`, and all eight files in that push (the verdicts file,
  five Stage 2 specs, the Stage 2 dataset manifest, and the Stage 2
  spec-hash record) were blob-compared against the evaluated local
  tree — **identical, 8/8**.
- **Spec-first:** all Stage 2 specs were written and SHA-256
  recorded at **2026-10-15T10:00:33Z, before any Stage 2 scoring**
  (`SPEC_HASHES_STAGE2.txt` on the branch): M6 `92d92c6e…`, M3
  `fd49b533…`, M29 `8299481c…`, M31 `5e0eb543…`, N1–N3 `9e005933…`,
  dataset manifest `c4ca98e6…`. Each evaluator verifies its spec
  hash at runtime and refuses to score on mismatch.
- **Model pin (all items):** main
  `83e0c396a4761ea3de80583be5e61e8ca2e07f9a` (current main at Stage 2
  start). Both evaluand files are blob-identical to the pins Stage
  1 and Phase 2 scored — `artifacts/free_models.py` blob
  `253b0c6d91840c906941216be117f2acc1497a57` (also at `2a713380c`,
  `12999fc22`); `sportsedge/pitcher_joint_engine.py` blob
  `00cba6f664e313b53ab0084e6f3f471a9d85b566` (also at `12999fc22`) —
  so every construction scored in this stage is byte-identical to
  the one its earlier legs were scored on.
- **Datasets** (`DATASET_MANIFEST_STAGE2.md` on the branch): the
  SBR corpus (reused from Stage 1, SHA-256 `3f952fd0…`, **not in
  the repo**), the StatsAPI transport cache for the pitcher items
  (6,175 payloads, combined identity `87841854…`, **not in the
  repo** — a re-acquirable public-API cache), and nflverse
  `games.csv` for N1–N3 (SHA-256 `a484c6ae…`, **not in the repo**;
  the file's line/odds columns were not read — see §5).

## 1. M6 — Team Total Runs, CAL leg

- Spec: `SPEC_M6_TEAM_TOTALS.md`, SHA-256
  `92d92c6ef1ae082b91940197571cf70fc474d2b7f1fc4459383dd70710ea6b43`.
- Evaluator: `scripts/eval_mlb_cal_legs.py` (shared with M3).
  Population: the identical M1/M2/M4 matched subset — model-only
  n = 10,237; paired (climatology-eligible) n = 10,092.
- Verification before scoring: dataset + audit SHA-256 verified;
  the M2 climatology was reconstructed independently in this
  evaluator and matched the published audit exactly (eligibility
  set identical on all 10,237 games; margin CRPS reproduction
  deviation ≤ 5.0e-07, the audit's rounding); full re-run
  reproduces the results JSON exactly except `generated_at`.

### VERDICT: DOES_NOT_BEAT_BASELINE

| Leg | CRPS |
|---|---|
| Lane A team Poissons (paired subset) | 1.7792 |
| League team-run climatology | 1.7181 |

- Paired ΔCRPS **+0.0611**, 95% CI [+0.0563, +0.0658] — entirely
  above zero.
- Every season worse, every CI entirely above zero (2021 +0.0504
  [+0.0423, +0.0585]; 2022 +0.0645; 2023 +0.0618; 2024 +0.0645;
  2025 +0.0658 [+0.0534, +0.0770]).
- Shape: mid-PIT deciles [0.035, 0.132, 0.447, 0.802, 0.968] vs the
  uniform [0.1, 0.25, 0.5, 0.75, 0.9] — a U-shape: the Poisson team
  marginals are **under-dispersed** against realized team scoring.
  The league's own raw run distribution — which has the true
  over-dispersion baked in — beats the model's per-team
  distributions on the model's home ground, team by team (home
  CRPS 1.7420, away 1.8163, both against the same climatology).
- Market leg: FORWARD_ONLY_BY_DESIGN (no historical team-total
  lines exist).

## 2. M3 — Alternate Run Lines, CAL leg

- Spec: `SPEC_M3_ALT_RUNLINE.md`, SHA-256
  `fd49b533b937e51fe6ad1924b6efe076d43317cbb4711318a206c60b6dae3202`.
- Evaluator: `scripts/eval_mlb_cal_legs.py`. Grid: 19 lines
  (half-lines −4.5…+4.5; integer lines −4…+4, pushes excluded per
  line with both scorers conditioned on resolution — the M4 rule).
  Paired n = 10,092 (identical matched subset).
- Verification: margin-PMF read proven equal to
  `model_probability` at all 19 lines on 50 games (max deviation
  2.0e-15); main-line cells reproduce the audit's own probabilities
  on the closing-spread subsets (max Brier deviation 7.9e-07, the
  audit's 6-dp rounding); determinism re-run exact.

### VERDICT: DOES_NOT_BEAT_BASELINE

- Pooled paired ΔBrier **+0.00353** [+0.00276, +0.00436];
  ΔLogLoss **+0.01554** [+0.01308, +0.01825] — both entirely above
  zero; every season worse on both metrics.
- Per-line: the model loses at **17 of 19 lines**. The exceptions
  are the cells nearest the main line: −1.5 is a statistical tie
  (ΔBrier −0.0002 [−0.00143, +0.00102]) and 0.0 crosses zero. The
  deficit **grows monotonically toward the tails** — +0.0037 at
  −4.5, +0.0056 at +4.5, +0.0073 at +3.5, +0.0083 at +3.0 — exactly
  where an under-dispersed margin distribution misprices covers.
  The alternate-line failure recorded by the phase-7 harness for
  totals (M5) is now confirmed for the run-line family as well,
  against a stronger baseline (expanding climatology, not a fixed
  naive rate) and on the identical walk-forward as the main legs.
- Market leg: FORWARD_ONLY_BY_DESIGN (corpus hangs only the ±1.5
  main).

## 3. M29 — Pitcher Pitches Thrown, CAL

- Spec: `SPEC_M29_PITCHER_PITCHES.md`, SHA-256
  `8299481c72609023a899f416959ee45b62a254b137ce4262e3a7a502130a1723`.
- Evaluator: `scripts/eval_mlb_pitcher_pitches_cal.py`. Population:
  the Phase 2 undercard population exactly — **n = 5,371 starts**
  (2024: 1,976; 2025: 3,395), reconciled start-by-start.
  Pitches-specific exclusions: **zero** — every fixture gameLog and
  every pool row carried a measured pitch count, so the engine's
  fail-closed pitch rule never fired.
- Verification: spec + dataset-manifest hashes verified at load;
  engine blob verified at the pin; pool code **byte-identical** to
  the undercard evaluator's (per-function hashes); production-pool
  parity **25/25 PASSED** (all 25 pools equal to
  `MLBPitcherPublicSource.prior_starts` with zero mismatched
  starts, zero date mismatches, equal stat lines); sweep sanity
  max deviation 5.6e-17 on 10 fixtures at the 85.5 line.

### VERDICT: DOES_NOT_BEAT_BASELINE

| Scorer | CRPS (pooled) |
|---|---|
| Engine (Jeffreys posterior on ≤12-start pool) | 7.0111 |
| B1 — pitcher's own trailing raw distribution | **6.7465** |
| B2 — league climatology | 6.9087 |

- ΔCRPS vs B1 **+0.2645** [+0.2279, +0.3051] — entirely above zero,
  in both seasons (2024 +0.2556; 2025 +0.2697).
- ΔCRPS vs B2 **+0.1024** [−0.0214, +0.2357] — the CI includes
  zero: against league climatology the engine is *not
  distinguishable*, but the gate requires beating both baselines
  and it beats neither.
- The levels are honest — mean predicted 88.0 pitches vs mean
  realized 87.9; central-80% interval coverage 0.794 against a
  0.80 nominal. What loses is the shape: the posterior's smoothing
  costs more than the raw pool's noise, the identical disease the
  Phase 2 undercard found in outs/hits/walks/earned runs. Pitches
  makes it **five for five**: every distribution this engine
  produces from a ≤12-start pool loses CRPS to the raw trailing
  distribution of that same pool. (Declared tail convention, as in
  Phase 2: CRPS is truncated at m = 170 for all three scorers; the
  engine's mean residual tail mass there is 0.0485 — the Jeffreys
  saturation past the pool maximum — so the truncation if anything
  flatters the engine. The deficit is conservative.)
- Registration: unchanged. #2264 remains the owner's governance
  decision; this measurement neither registers the family nor
  argues the question either way. Market leg:
  FORWARD_ONLY_BY_DESIGN.

## 5. N1–N3 — NFL calibration legs

- Spec: `SPEC_N1_N3_NFL_CALIBRATION.md`, SHA-256
  `9e005933cda2cabfbc673140ab5093f9395d5032e3965d1037caa90e65828d60`.
- Evaluator: `scripts/eval_nfl_calibration.py`. Corpus: nflverse
  `games.csv` (SHA-256 `a484c6ae…`, hash-verified at load; only
  schedule/score fields read — the file's line columns were never
  accessed). Population reconciles exactly: **2,127 REG games,
  2018–2025, all scored** (256 ×3 seasons, 271 in 2022, 272 ×4);
  paired subset n = 1,887 (240 climatology-ineligible, 30 per
  season, counted).
- **Verification — the strongest in the lane's history.**
  Probability parity PASSED: wherever `calculate()` returns a Lane
  A view, its probabilities equal the direct
  `context_for → score_means → model_probability` pipeline
  **bit-exactly** — 75/75 row checks at 0 ulp — and both the direct
  pipeline and `calculate()`'s own exported means reproduce
  bit-exactly across three independent worktrees. One real
  discrepancy was found and recorded, not smoothed over:
  `calculate()` carries an NFL critical-context gate
  (`BLOCKED_NFL_CRITICAL_CONTEXT_UNVERIFIED`) that refuses some
  no-history fixtures (week 1: 0 prior same-season games) *before
  pricing*, while the direct construction scores them with the
  production 0.0 ratings — the spec §5 population includes those
  fixtures. **The gate changes availability, not probabilities:**
  the verdicts below measure the rating construction's
  probabilities, proven identical to `calculate()`'s wherever it
  prices. (The paired subsets the gates are decided on are barely
  touched by this: climatology eligibility already excludes each
  season's first 30 games.) Determinism: probability-level double
  run, max deviation 0 ulp across all five scored quantities.

### N1 VERDICT: BEATS_BASELINE — the program's first

| Scorer | Brier | Log loss |
|---|---|---|
| Model (`calculate()` Lane A) | **0.2393** | **0.6716** |
| B1 — margin climatology implied | 0.2502 | 0.6935 |

- Paired ΔBrier **−0.01082** [−0.01326, −0.00840]; ΔLogLoss
  **−0.02193** [−0.02684, −0.01703] — both CIs entirely below
  zero. **Every season 2018–2025 is negative on both metrics**,
  and every season's ΔBrier CI is entirely below zero.
- Read plainly: the ≤5-game margin rating (× 0.12, capped ±3)
  carries real team-strength signal for who wins NFL games —
  signal the league's own margin distribution does not have.
  Against **this** baseline. There is no market leg (forward-only
  by design), so this validates nothing and promotes nothing; it
  is the first construction in the program that beat any baseline
  it was gated against.

### N2 VERDICT: BEATS_BASELINE

- Margin-distribution CRPS: model **7.8389** vs climatology
  8.0434; paired Δ **−0.2045** [−0.2613, −0.1479] — CI entirely
  below zero. Point estimate negative in all 8 seasons (5 of 8
  season CIs entirely below zero; 2020/2022/2023 cross zero).
- The margin distribution the spread family prices from is, on
  this evidence, better than the league's raw margin history —
  the Normal(13.7) shape around a rating-driven mean is doing
  real work. Same baseline-only caveat as N1.

### N3 VERDICT: DOES_NOT_BEAT_BASELINE

- Total-distribution CRPS: model 7.8225 vs climatology
  **7.7126**; paired Δ **+0.1099** [+0.0283, +0.1987] — CI
  entirely above zero.
- The failure concentrates exactly where the construction says it
  should: **2020, Δ +0.5879 [+0.1848, +1.0086]** — a season whose
  scoring level jumped (empty-stadium year) against a total mean
  that is a frozen 22-points-per-team prior plus a margin-form
  split. The run measures the missing absolute scoring-rate model;
  it does not excuse it, and the card keeps
  `WATCH_NFL_TOTAL_PRIOR_ONLY` whatever this number had said.
- The split inside one engine is the finding: **the same ratings
  that beat climatology on margins and wins lose to it on
  totals**, because the margin form is where the rating
  information lives and the total was never given a level model
  at all.

## 4. M31 — EITHER_PITCHER dependence audit (HA / BB / ER)

- Spec: `SPEC_M31_EITHER_DEPENDENCE.md`, SHA-256
  `5e0eb54368b35094e58de4300185e5f28d0e48bb1dfb9cda1c02b02917d65153`,
  plus **Amendment 1** (below). Evaluator:
  `scripts/eval_mlb_either_dependence.py`. Population: **2,160
  scored game pairs** (2024: 765; 2025: 1,395) — both starters in
  the undercard population, paired by game; 1,051 gamePks lost to
  PAIR_SIDE_MISSING (counted, by season); zero pair anomalies.
- Verification: spec + manifest hashes verified; pool code
  byte-identical to the undercard lineage; single-pitcher lineage
  parity inherited from M29's 25/25 PASSED on the identical pools.
  **Event-semantics hand-check far beyond the spec minimum:** an
  independent Cartesian re-derivation (Jeffreys posterior
  re-derived from the single-pitcher formula) reproduced the
  engine on 1,546 checks across 773 pairs at HA X+ 6 and or-fewer
  3 — max deviation 3.3e-16 — including the dispositioned calls
  Amendment 1 requires.

### The engine defect, and Amendment 1

The first pass **stopped**, correctly, under the spec's
no-substitutes rule: of 51,840 either-calls, **110 refused** (68
pairs) — every one a full-coverage event whose uniform-weight
Cartesian sum is 1.0000000000000002, one floating-point ulp above
1, tripping the engine's own settlement-mass validation. The
stopped record (verdict `STOPPED_ENGINE_EITHER_MASS_ERROR`, full
failure census) is preserved inside the final results file.
**Amendment 1** (`AMENDMENT_M31_ULP_DISPOSITION.md`, SHA-256
`f1b55887489710d87d7d1ecd7b152d0ebfb12021129733742055e54fd189585f`,
filed after the stop and before any measurement existed)
declared the only permitted recovery: an independent `math.fsum`
recomputation must show the refusal is a pure summation artifact
(mass within 1e-12 of the boundary), and the probability is then
the **pinned module's own `_posterior`** evaluated at the
exactly-summed masses. All 110 refusals qualified; zero were
undispositionable; every dispositioned call is flagged in the
audit. The defect itself — the either branch's summation tripping
its own validation on full-coverage events — is recorded here as
a **defect finding for the engine's owners**; this lane changed
no engine code.

### VERDICT: DEPENDENCE_MEASURED — and the dependence is ≈ 0

Residual correlation between the two starters' outcomes
(posterior-mean residuals, the instrument built to isolate
dependence from marginal error), pooled n = 2,160:

| Stat | Pearson ρ | 95% CI | Spearman ρ |
|---|---|---|---|
| HA | −0.006 | [−0.044, +0.029] | −0.004 |
| BB | +0.009 | [−0.033, +0.047] | +0.008 |
| ER | +0.001 | [−0.042, +0.048] | −0.001 |

After each pitcher's own expected level is accounted for, the
two starters in the same game are **not measurably correlated**
in 2024–2025 history; the intervals exclude dependence above
roughly +0.05. The shared-game channels the design package
worried about (park, weather, umpire, game script) do not appear
as residual co-movement at this sample size.

### But the either-probabilities are materially wrong anyway — from the marginals

Mean signed error (predicted − observed) of the independence
either-probability, materiality per the declared standard (CI
lower bound > +2pp):

| Cell | Pred | Obs | Error | Reading |
|---|---|---|---|---|
| BB X+ 4 | 0.210 | 0.163 | **+0.047** [+0.030, +0.063] | **MATERIAL** |
| BB X+ 5 | 0.100 | 0.052 | **+0.048** [+0.039, +0.058] | **MATERIAL** |
| BB X+ 6 | 0.059 | 0.009 | **+0.050** [+0.046, +0.054] | **MATERIAL** |
| HA X+ 10 | 0.098 | 0.057 | **+0.041** [+0.030, +0.051] | **MATERIAL** |
| HA X+ 5 | 0.782 | 0.825 | −0.043 [−0.061, −0.027] | significant understatement |
| ER X+ 3 | 0.629 | 0.671 | −0.042 [−0.061, −0.023] | significant understatement |
| BB or-fewer 2 | 0.888 | 0.941 | −0.053 [−0.064, −0.043] | significant understatement |

The error is **monotone in the threshold for all three stats**:
understated at low X+ rungs, overstated and growing into the far
tail (HA X+ 8/9: +0.020/+0.029; ER X+ 6: +0.025). That is the
signature of the single-pitcher marginals' shape — the Jeffreys
posterior on a ≤12-start pool is over-dispersed against realized
outcomes, too thin in the center, too fat in the tail — the same
over-dispersion Phase 2 measured by CRPS and M6 saw as U-shaped
PIT. The or-fewer forms show **no material overstatement at any
threshold** for any stat.

**The two-part answer to the owner's question.** (1) Independence
is not the either-market's problem on this evidence: measured
dependence is zero within tight intervals. (2) The
either-probabilities are still materially wrong at exactly the
rungs a buyer would touch — BB X+ 4/5/6 overstated by ~5 points
(at 6+, the construction states 0.059 where history realizes
0.009) and HA X+ 10 by ~4 points — because they inherit the
marginals' tail error. Repairing dependence alone would fix
nothing; the marginals have to be repaired first, which is the
model-fix lane's shrunk-variant program, not a combination-rule
change. Whether the family's gate should now be re-named from
the dependence blocker to the marginal defect is the owner's
ruling; per the brief, the family state is unchanged by this
audit: `EITHER_PITCHER_DEPENDENCE_UNMEASURED` stands as
assigned, no intake, no pricing.

## 6. Synthesis — what Stage 2 adds to the refine/recalibrate picture

**Lane A is now measured on every leg it prices, and the deficit
grows with the richness of the object priced.** Moneyline Brier
deficit vs the market +0.0115 (M1), run line +0.0186 (M2), totals
+0.0224 (M4); against naive baselines the same construction loses
on team totals (M6, ΔCRPS +0.0611, CI tight) and on all 19
alternate run lines pooled (M3, ΔBrier +0.00353 [+0.00276,
+0.00436]). There is no Lane A surface left unmeasured, and no
leg on which it wins. The consistent ordering — the deficit
scales with how much of the run distribution the market is
pricing — says the market's edge over Lane A is
*distributional*: two independent Poissons on shrunk trailing
means carry less information about run distributions than the
price does, everywhere, in every season measured.

**The pitcher engine's disease is one disease, six times.**
Outs, hits allowed, walks, earned runs (Phase 2), pitches (M29),
and now the either-combinations (M31) all fail the same way:
honest levels, wrong shape — a ≤12-start pool, Jeffreys-smoothed,
is over-dispersed against reality and loses CRPS to its own raw
trailing distribution. M31 adds the sharpest localization yet:
the combination rule is *not* an additional problem (starter
dependence ≈ 0, tightly), and the either-error is the marginals'
error viewed through max/min. Any repair program that starts
with dependence modeling is starting in the wrong place; the
marginals are the defect, and the Phase 2 prescription stands —
shrink harder, as a challenger, under new preregistration.

**The NFL engine is the program's first split decision, and the
split is informative.** The same ≤5-game margin rating beats
climatology on wins (N1) and margins (N2) — genuinely, in every
season, against the baseline it was gated on — and loses on
totals (N3) because totals were never given a level model, only a
frozen prior. Signal lives where the construction put information
(the margin form); absence lives where it didn't (the total
level). Beats-baseline is not beats-market — the NFL market legs
remain forward-only by design, and nothing here validates or
promotes anything — but as a calibration matter, the NFL rating
core is the first construction in the program with positive
out-of-sample evidence against any baseline.

**Net state after Stage 2:** every queued calibration leg in the
owner's set is now run. The matrix's EVALUABLE_NOW set drops from
8 rows to **1** (M47, ladder forms whose underlying distributions
Phase 2 already scored). What remains unmeasured is unmeasured
for named reasons only: owner-held preregistrations
(PREREGISTERED_HELD ×12 + STARTER_CERTAINTY §6), forward-only
market legs awaiting prospective paired data, and families with
no engine yet (NOT_EVALUABLE ×78 — the wiring lane's build
queue). **Validated profitable families remain zero. PLAY
remains unavailable.**

## 7. Matrix fold-back and verification record

- Matrix (`~/workspace/sportsedge/backtest_program_20261014/MATRIX.md`)
  amended 2026-10-15 with cause, per row: M6 and M3 (§1–§2), M29
  (§3), M31 (§4), N1–N3 (§5) moved to EVALUATED_WITH_VERDICT with
  their verdicts and evidence classes in-row. Counts: verdicts
  37 → **44** (MLB 29 → 33, NFL 4 → 7), EVALUABLE_NOW 8 → **1**
  (M47 only); all other states unchanged; row arithmetic
  re-verified (51/56/18/13 = 138).
- Per-item verification, stated exactly: M6 and M3 —
  JSON-identical determinism re-runs, plus an independent
  climatology reconstruction matching the Stage 1 audit's
  eligibility set and margin CRPS exactly. N1–N3 — probability
  parity bit-exact (75/75) and 0-ulp probability determinism
  across three worktrees. M29 — production parity 25/25 and
  byte-identical pool lineage. M31 — 1,546 independent
  event-semantics checks (max deviation 3.3e-16) including the
  Amendment-1 dispositioned calls; the stopped first pass and its
  census are preserved in the results file.
- Publication: specs, the dataset manifest, the hash record,
  Amendment 1, all four evaluators, all five results files, the
  Stage 1 supplementary verdicts file, and this report are on
  branch `research/mlb-market-legs-20261014`, held unmerged, every
  file blob-compared against its local copy after the push (the
  publication head is recorded in the lane's closing report to
  the owner; the branch itself is the record).
- Nothing in this stage changed a model, a registry, a
  threshold, a gate, or an eligibility flag. The M31 engine
  defect (§4) is reported, not repaired — repair belongs to the
  engine's owners under the standing blocker workflow.

*Stage 2 closed 2026-10-15. Stage 1 report: `REPORT.md` in this
folder. Program record: `~/workspace/sportsedge/backtest_program_20261014/REPORT.md`
and `MATRIX.md`.*



