# CFB train/freeze pre-attempt status — 2026-09-19

The selected-candidate serving gap is closed. All four frozen candidate families are executable through a hash-bound selected-candidate artifact and the canonical runtime adapter, with hosted direct-vs-adapter distribution parity tests.

The frozen model-selection budget remains 0 of 4 attempts consumed and no candidate evaluation has been performed. Model_P, Truth Gate, promotion, eligibility, staking, evidence-clock, backfill, and OFFICIAL authority remain false.

The reconstructed-selection MATERIALIZE_ONLY workflow was rerun on current main after the evaluator runtime dependency repair. The contract tests passed, the authenticated CFBD provider preflight passed account authentication, and the reconstructed historical weather transport contract passed without requiring paid CFBD weather. Acquisition then stopped fail-closed before the first historical replay call with `CFBD_REPLAY_PLAN_EXCEEDS_REMAINING_QUOTA`.

The frozen acquisition plan requires 244 planned CFBD historical calls plus a 50-call reserve. Acquisition must not begin unless the provider reports enough remaining quota for the complete frozen plan and reserve. Do not reduce the plan, reserve, seasons, weeks, candidate inputs, or source contract merely to fit the currently available quota.

No historical replay call was made by the blocked preflight/materialization run. The candidate evaluation budget therefore remains untouched at 0 of 4.

Reconstructed historical data remains `RECONSTRUCTED_HISTORICAL_NOT_PIT` and cannot be relabeled as promotion evidence. A successful future MATERIALIZE_ONLY run may materialize and hash-bind the frozen reconstructed-selection bundle, but it still grants no Model_P, Truth Gate, promotion, eligibility, staking, evidence-clock, backfill, or OFFICIAL authority.
