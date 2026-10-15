# Verdicts — M2 (run line) and M4 (totals), 2026-10-14

**Label: RESEARCH_EVIDENCE — retrospective-diagnostic evidence class**
(untimestamped SBR closes; NOT strict-contract validation; promotes
nothing; no model/registry/threshold changed).

**Evaluator commit (this branch):**
`220643b4d61775dbf5907eedc28a69c733577f48` — the commit whose tree
carries the evaluators, specs, manifest, and results JSONs below.
Base/model pin: main `2a713380c7d49733577c238a126f487382634040`
(`artifacts/free_models.py`, Lane A).

**Corpus:** `mlb_odds_dataset.json`, SHA-256
`3f952fd0bfae9f4f2d17e66692cb936ce6e1a5f6b415318012090c85933b882b` —
**not in this repo**; see `DATASET_MANIFEST.md` for source and
acquisition. Reproduction: `REPRODUCE.md` (verified end-to-end from a
fresh checkout of this branch by the evaluating lane — all three
results JSONs reproduce exactly except `generated_at`).

## M2 — Run Line ±1.5 MARKET leg: DOES_NOT_BEAT_MARKET

- Spec `SPEC_M2_RUNLINE.md` SHA-256
  `68c7020fef4df5bb9ab132dcf43b652b4ffcb57cff92e49cde30949e780785b6`
  (hashed before scoring).
- Matched n = 10,237 (identical subset to M1). Brier 0.259303 vs
  market 0.240678; **ΔBrier +0.018625 [+0.015426, +0.021760];
  ΔLogLoss +0.041808 [+0.034755, +0.048710]** — both CIs entirely
  above zero; every season worse.
- Full record: `results_m2_runline.json`.

## M4 — Total Runs main MARKET leg: DOES_NOT_BEAT_MARKET

- Spec `SPEC_M4_TOTALS.md` SHA-256
  `fd644387d84eb243febe63276321c5d6cbd525bbe7aa3e73c6008cd99e347c56`
  (hashed before scoring).
- Matched-with-total 10,239; push-outcome exclusions 286
  (predeclared); scored n = 9,953. Brier 0.271967 vs market 0.249537;
  **ΔBrier +0.022430 [+0.019004, +0.026036]; ΔLogLoss +0.060423
  [+0.048912, +0.074694]** — both CIs entirely above zero; every
  season worse.
- Full record: `results_m4_totals.json`.

Lane A's three measured market deficits on the identical
walk-forward now read: moneyline (M1) +0.0115, run line +0.0186,
totals +0.0224 ΔBrier — the deficit grows as the market prices more
of the distribution. Lane report:
`~/workspace/sportsedge/mlb_market_legs_20261014/REPORT.md`.
