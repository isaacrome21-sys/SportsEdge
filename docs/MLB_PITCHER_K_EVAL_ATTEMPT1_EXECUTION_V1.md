# MLB pitcher-K evaluation Attempt 1 execution bridge

This is the governed one-shot execution bridge for the frozen pitcher-K
candidate-specific historical test.

The connected GitHub capability cannot initiate workflow_dispatch, so the bridge
uses the repository's established single-main-push marker pattern. The workflow
runs only when `config/research/mlb_pitcher_k_eval_attempt1_dispatch_v1.json`
lands on `main`.

The run:

1. validates the exact Attempt-1 marker;
2. materializes PIT-safe 2023–2025 rows;
3. runs the frozen evaluator once;
4. uploads rows/evaluation/summary as an Actions artifact;
5. on success, persists an immutable readout and receipt to the `data` branch.

This is a candidate-development readout only. Historical reconstruction is
explicitly not forward evidence, and the run cannot grant Model_P, promotion,
staking, OFFICIAL, or bettor-facing authority.
