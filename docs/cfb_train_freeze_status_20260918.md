# CFB train/freeze repair status — 2026-09-18

This branch restores the machine-verified post-PR-833 candidate preregistration refreeze and adds the guarded reconstructed-selection acquisition/materialization lane needed before candidate evaluation.

The new `cfb-train-freeze` entrypoint intentionally stops after the zero-cost CFBD provider preflight. It does **not** spend one of the four frozen candidate attempts until the selected-candidate serving contract can faithfully execute all four preregistered families, including `GAMES_IN_SAMPLE_FEATURE`, in the production joint-distribution runtime.

Current authority remains zero: no Model_P, Truth Gate, promotion, eligibility, staking, evidence-clock, backfill, or OFFICIAL authority is created by these repairs. Reconstructed historical data remains `RECONSTRUCTED_HISTORICAL_NOT_PIT` and cannot be relabeled as promotion evidence.

The remaining external prerequisite is a repository Actions secret named exactly `CFBD_API_KEY`; secrets cannot be added through the connected GitHub App. The preflight must verify the account, weather entitlement, remaining quota, and the frozen replay-call budget before any historical acquisition begins.
