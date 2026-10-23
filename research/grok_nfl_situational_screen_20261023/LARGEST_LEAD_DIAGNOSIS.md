# LARGEST_LEAD v1: why it loses to naive (diagnostic only, Oct 23, 2026 CT)

Status: DIAGNOSTIC_ONLY. Nothing below is adopted; there is no re-tuning on the
held-out seasons 2019–2025. LARGEST_LEAD stays refused with NAIVE_FAIL.
Numbers come from `diagnose_largest_lead.py` → `largest_lead_diagnosis.json`
(1,871 held-out games; mean log loss per game).

| Variant | Mean log loss |
|---|---:|
| Naive, earlier seasons, +0.5 Laplace (the screen baseline) | 3.2285 |
| Naive, same pool, unsmoothed | 3.3382 |
| v1 model, after the same +0.5 Laplace | 3.4950 |
| v1 model as declared (unsmoothed) | 3.6174 |

The v1 gap of +0.389 has two parts:

1. **Zero-mass outcomes (about 0.12–0.19 of the gap).** v1 shifts an
   unsmoothed empirical pmf, so 17 games land on lead values with
   essentially no mass. They alone add 0.188 to v1's mean. The baseline gets
   +0.5 Laplace smoothing; v1 does not. That makes the comparison partly a
   smoothing comparison: smoothing alone is worth 0.110 even on the naive
   pool.
2. **The team-strength shift itself (about 0.27 of the gap).** It still hurts
   after the same smoothing (3.4950 vs 3.2285). Two declared constants are
   the likely cause:
   - `LEAD_REF = 3.0` sits below the typical rating gap. The mean shift is
     +0.77 points, so v1 pushes the whole distribution toward bigger leads in
     the average game.
   - Fractional shifts are split linearly between neighbouring integers. That
     smears mass off football's key lead values (3, 7, 10, 14, …) onto values
     that rarely occur.

A future version would need to be declared before seeing any new data and
screened on data not used here. That means pre-specified smoothing, a
lattice-preserving shift and a LEAD_REF taken from earlier seasons only.
