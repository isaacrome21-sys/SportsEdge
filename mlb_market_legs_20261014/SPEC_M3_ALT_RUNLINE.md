# MLB Lane A Alternate Run Lines — Calibration Spec (M3)

- **Spec written:** 2026-10-15 (before any alternate-line score was
  computed by this lane). Stage 2 of the MLB market-leg lane; Stage 1
  discipline applies throughout.
- **Label of any output:** RESEARCH_EVIDENCE — retrospective,
  development data. **Calibration leg only.** The market leg of the
  alternate lines is **FORWARD_ONLY_BY_DESIGN**: the SBR corpus hangs
  only the ±1.5 main line; no historical alternate-line pairs exist.
  This evaluation promotes NOTHING and changes no model, registry
  entry, or threshold.
- **Question:** On the identical matched subset scored by M1/M2/M4,
  do Lane A's cover probabilities at alternate run lines beat the
  expanding league margin climatology's cover probabilities against
  realized margins?

## 1. Model identity (exact)

- Code and pin: identical to SPEC_M6 §1 (`artifacts/free_models.py`
  @ main `83e0c396a4761ea3de80583be5e61e8ca2e07f9a`, blob
  `253b0c6d91840c906941216be117f2acc1497a57`, identical to the Stage 1
  pin). Means read from the same hash-verified Stage 1 audit
  artifact (`audit_m2_runline.csv`, SHA-256
  `b0b39ab2a92e2114ed4ecaa9b0823396fb28bbd917d248e8cf448b82967b39dc`),
  verified at load.
- Cover probability at home spread s:
  `model_probability("MLB", "SPREAD", "HOME", s, home_mean,
  away_mean)` from the module itself — the same independent-Poisson
  joint as the ±1.5 leg, no reimplementation.

## 2. Declared line grid

The DK catalog's alternate run-line range is −4.5…+5 (CATALOG_MLB,
Oct 13 board). The evaluation grid is declared here (a calibration
leg needs no market lines; the grid spans the catalog range):

- Half-lines (no pushes possible): s ∈ {−4.5, −3.5, −2.5, −1.5,
  −0.5, +0.5, +1.5, +2.5, +3.5, +4.5}. The −1.5/+1.5 cells reproduce
  the M2 main-line geometry from the home side and serve as an
  internal consistency check against M2's published numbers.
- Integer lines (pushes possible): s ∈ {−4, −3, −2, −1, 0, +1, +2,
  +3, +4}. Push games (realized margin exactly −s) are excluded
  from that line's scoring for BOTH scorers and counted per line —
  the M4 conditioning rule: both probabilities are renormalized
  conditional on resolution (model: win/(win+loss) from
  `model_probability`'s (win, push); baseline likewise from the
  empirical margin distribution).

## 3. Population and baseline

- Population: the identical matched subset (audit INCLUDED,
  n = 10,237); the gated pooled comparison uses the
  climatology-eligible paired subset (n = 10,092, the M2 §8 rule).
- Baseline **B1 — league margin climatology:** the empirical
  distribution of home margins over strictly prior same-season
  games outside the sealed window [2024-07-01, 2024-09-01),
  recomputed from corpus scores (the M2 §8 comparator). Baseline
  cover probability at s: P̂(margin + s > 0), conditioned on
  resolution for integer lines per §2.

## 4. Metrics and the predeclared bar (calibration leg)

- Per (game, line): Brier and log loss (probabilities clamped at
  1e-15) of the home-cover event y = 1{margin + s > 0} on resolved
  games, model vs B1.
- Per-game paired statistic: the mean over the 19 grid lines of the
  per-line Brier difference (model − B1), and likewise for log
  loss. Pooled ΔBrier and ΔLogLoss with 95% percentile CIs, block
  bootstrap over ISO calendar weeks, 2,000 resamples, seed
  20261015.
- **Gate (declared before results):** BEATS_BASELINE iff pooled
  ΔBrier CI entirely < 0 AND pooled ΔLogLoss CI entirely < 0.
  Otherwise DOES_NOT_BEAT_BASELINE, CI positions reported.
- Descriptive (not gated): the full per-line table — n resolved,
  pushes excluded, mean model prob, mean baseline prob, realized
  cover rate, Brier model vs B1, per-line paired ΔBrier CI — plus
  the same table split by season for the main-line cells.

## 5. Verification required before the verdict is reported

- **Internal consistency:** the s = −1.5 and s = +1.5 cells,
  recombined to the M2 orientation (home cover at the game's own
  closing spread), must reproduce M2's published model Brier on the
  matched subset to < 1e-9 (the grid cells are the same joint read
  at fixed lines; the M2 number is the per-game closing-line read —
  the check is run on the subset of games whose closing spread
  equals the cell line, where the two must agree exactly).
- **Artifact identity and determinism:** as SPEC_M6 §5.

## 6. What any verdict does and does not unlock

As SPEC_M6 §6, for the alternate-line readouts: calibration
evidence about the margin distribution's shape away from the main
line. No market verdict, no eligibility, no activation input —
reported in full either way.
