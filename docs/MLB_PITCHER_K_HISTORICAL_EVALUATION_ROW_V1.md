# MLB pitcher-K historical evaluation row v1

Status: **candidate-test reconstruction only; never forward evidence**.

This adapter closes the provenance gap between the live Statcast binding and the
frozen 2023–2025 pitcher-K candidate test. Historical rows do **not** impersonate
the live `SPORTSEDGE_STATCAST_MAIN_PROVENANCE_V1` receipt.

For a historical target start, Baseball Savant is queried with the official game
date as an exclusive upper bound. The resulting receipt is
`MLB_PITCHER_K_HISTORICAL_STATCAST_PROVENANCE_V1` and must state:

- historical reconstruction / backfill = true;
- same-day rows included = false;
- future rows included = false;
- forward-evidence eligibility = false;
- promotion authority = false.

The adapter binds those features into the same research candidate feature schema
so the frozen formula remains unchanged. The row is explicitly tagged
`CANDIDATE_SPECIFIC_HISTORICAL_TEST_ONLY`.

For the evaluation baseline, the row prices every 0.5–19.5 K threshold through
the shipped `pitcher_joint_engine` using the same 5–10 strictly-prior start
pool and the same validated opponent/lineup K adjustment. The resulting
incumbent probabilities are evaluation comparators only and never model-fit
features.

This contract creates no Model_P, Truth Gate, promotion, staking, OFFICIAL, or
bettor-facing authority.
