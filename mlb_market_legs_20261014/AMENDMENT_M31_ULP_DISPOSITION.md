# AMENDMENT 1 to SPEC_M31_EITHER_DEPENDENCE — engine ulp disposition

- **Written:** 2026-10-15, after the M31 evaluator's first pass
  stopped (verdict `STOPPED_ENGINE_EITHER_MASS_ERROR`, recorded in
  its results file) and **before any M31 measurement was produced
  or reported**. The stop exposed a mechanical fact about the
  engine (which calls refuse, and why), not any calibration
  outcome; this amendment is written against the failure census
  only. Filed and hashed before the M31 scoring re-run, per the
  program's amendment precedent (Phase 2 filed two amendments with
  cause). The parent spec is not edited; its SHA-256 stands.
- **The defect, as censused by the stopped run:** of 51,840 engine
  either-calls over 2,160 scored pairs, 110 refused (68 pairs
  affected). Every refusal is a **full-coverage event** — the
  either-event holds for all Cartesian pool states — whose
  uniform-weight Cartesian sum is 1.0000000000000002: the raw event
  mass exceeds 1 by one floating-point ulp (or its complement is
  −2.2e-16), and the engine's settlement-mass validation refuses
  it. The intended probability is the engine's own Jeffreys
  posterior at raw mass exactly 1; no outcome information is
  involved in the failure.

## Declared disposition (the only change)

Where `price_pitcher_market` refuses an either-call, the evaluator
may recover the probability **only** if all of the following hold,
checked per call:

1. An independent recomputation of the Cartesian state masses —
   using `math.fsum` over the same raw pools in the canonical
   configuration — shows the event mass within **1e-12** of a
   boundary (exactly-full coverage: event mass ≈ 1 and complement
   ≈ 0, or the symmetric ≈ 0 case), i.e. the refusal is a pure
   float-summation artifact.
2. The probability is then produced by the **pinned module's own
   `_posterior`** evaluated at the fsum masses (over / under /
   push assigned exactly as the either branch assigns them, eff =
   min of the two pools' effective sample sizes as the branch
   computes it) — the engine's arithmetic on exactly-summed
   masses, not a substitute formula and not a clamped engine call.
3. The call is flagged `ENGINE_ULP_DISPOSITION` in the audit CSV
   and counted in the results file, by (stat, form, threshold)
   cell, beside the original failure census.

Any refusal not satisfying (1) stops the run, as before. No other
engine output may be substituted for any call, under any
circumstances.

## Additional verification (added by this amendment)

The parent spec §6 event-semantics hand-check (≥ 10 pairs) must
include **≥ 3 dispositioned calls**, reproduced independently to
< 1e-9 by the same hand computation.

## What does not change

Everything else in SPEC_M31: population, grids, measurements,
reading rule, verdict form (`DEPENDENCE_MEASURED`), and the
family's unchanged state (`EITHER_PITCHER_DEPENDENCE_UNMEASURED`;
no intake, no pricing, no gate change). Separately, the engine
defect itself — the either branch's Cartesian summation tripping
its own settlement-mass validation on full-coverage events — is
recorded in the Stage 2 report as a defect finding for the
engine's owners; this lane does not modify engine code.
