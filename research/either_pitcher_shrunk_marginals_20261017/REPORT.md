# EITHER_PITCHER shrunk marginals — 2026 result (RESEARCH_EVIDENCE, calibration only)

Prereg `1cc6c4eb…8dae` (hash checked at run), Amendment 1 (pushed `199a2a3b` before any 2026 score).
Engine blob `00cba6f6`. K = 10, seed 20261017, 2,000 ISO-week block resamples.
Data: staging run 39026089063 (ACQUIRED_POSTHOC_FROM_PUBLIC_STATSAPI; not pregame snapshots, not #2344 originals).

**Pre-score checks:** FROZEN-arm reproduction of M31 2024 (765 pairs): max |Δ| = 0.0 → passed.
FROZEN 2026 used M31 Amendment-1 ulp dispositions on 52 cell calls (boundary-verified). Determinism: two runs byte-identical. Hand check (`handcheck_either.py`, no evaluator import, own pairing):
also finds 1,396 eligible pairs; 864 cell values from 12 random pairs match < 1e-9.

**2026 population:** 4,858 regular-season starts; 1,467 excluded (pool < 5); 1,396 pairs scored; 599 PAIR_SIDE_MISSING; 0 anomalies.

## Verdicts (per prereg §4) — all three: **DOES_NOT_BEAT_BASELINE**

ΔBrier = CHALLENGER − arm, pooled over the stat's cells, 95% CI:

| Stat | vs FROZEN | vs B1⊗B1 | vs B2⊗B2 (league) | Tail cells > +2pp |
|---|---|---|---|---|
| HA | −0.00675 [−0.00869, −0.00491] | −0.00714 [−0.00938, −0.00520] | −0.00146 [−0.00296, **+0.00004**] | none |
| BB | −0.00780 [−0.00930, −0.00629] | −0.00729 [−0.00887, −0.00598] | −0.00026 [−0.00114, +0.00066] | none |
| ER | −0.00825 [−0.01013, −0.00642] | −0.00897 [−0.01098, −0.00711] | +0.00061 [−0.00093, +0.00214] | none |

Failing leg in every case: vs B2⊗B2. ER failure was declared expected (§4).

## What it means (descriptive, not a verdict)

- The M31 tail defect is repaired: BB 6+ either realized 1.50%, CHALLENGER 1.73%, FROZEN 6.42%;
  HA 10+ realized 4.58%, CHALLENGER 4.40%, FROZEN 9.08%. Tail materiality passes for all stats.
- But per-pitcher information on top of the league distribution adds no proven value at the pair level;
  HA misses the gate by a CI upper bound of +0.00004.
- Gate `EITHER_PITCHER_MARGINAL_TAIL_ERROR` stays in place. No promotion, no market use. K is not re-tuned.
