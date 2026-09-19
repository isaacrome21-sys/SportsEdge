# CFB train/freeze pre-attempt status — 2026-09-18

The selected-candidate serving gap is closed on this branch. All four frozen candidate families are executable through a hash-bound selected-candidate artifact and the canonical runtime adapter, with hosted direct-vs-adapter distribution parity tests.

The frozen model-selection budget remains 0 of 4 attempts consumed and no candidate evaluation has been performed. Model_P, Truth Gate, promotion, eligibility, staking, evidence-clock, backfill, and OFFICIAL authority remain false.

The first evaluation is still blocked by the reconstructed-selection acquisition contract. The authenticated CFBD provider preflight verifies the account and quota budget, but the current account does not have the weather endpoint entitlement required by the frozen acquisition plan. No historical replay call has been made by the preflight, and acquisition must remain fail-closed until that provider/source-contract requirement is satisfied.

Reconstructed historical data remains `RECONSTRUCTED_HISTORICAL_NOT_PIT` and cannot be relabeled as promotion evidence.