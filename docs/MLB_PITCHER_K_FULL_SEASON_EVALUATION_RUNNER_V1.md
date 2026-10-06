# MLB pitcher-K full-season evaluation runner v1

This runner is the canonical consumer for the already-frozen pitcher-K candidate
evaluation. It does not acquire data and does not choose a new sample.

Input must be the full 2023–2025 PIT-safe rows artifact produced by the historical
materializer. The runner verifies the artifact's three-season identity, zero
forward/promotion authority, unique row identity, and at least 500 eligible 2025
candidate-test starts before the one-look can be consumed.

It then calls the merged frozen evaluator unchanged. The output is historical
candidate-development evidence only and cannot create Model_P, promotion, staking,
OFFICIAL, or bettor-facing release authority.
