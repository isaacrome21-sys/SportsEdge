# MLB context-adjusted rerun plan — 2026-09-29

This note records the defect exposed by the Sept. 29 Wild Card card before any predictive change is attempted.

## Observed defect

The manual snapshot workflow currently prices the card before it acquires starters, lineups, park, weather/roof, Statcast, umpire, and bullpen context. Those context lanes are explicitly presentation-only and `model_p_eligible=false`, so adding them to the rendered card cannot move Model_P.

The full-game shared engine also receives only `away_mean_runs` and `home_mean_runs`. On the canonical manual feature path those means are each club's own last-30 runs scored; opponent run prevention, the current probable starter, bullpen, park, and weather are not in the full-game run means.

## Research-only repair lane

Do not silently change production Model_P. Build a separate `NOT_MODEL_P` research lane that:

1. builds a strictly-prior full-game baseline from offense runs-for blended with opponent runs-allowed;
2. adjusts the opponent component for the confirmed/probable starter using strictly-prior start ER and outs, with starter workload share derived from prior outs;
3. consumes NWS/roof provenance before pricing;
4. applies weather only when outdoor exposure is known and the weather rule is explicitly versioned; retractable-roof `UNKNOWN` stays neutral/fail-closed;
5. reruns the existing SportsEdge shared full-game distribution from the adjusted run means;
6. reports baseline-vs-research probabilities and edge deltas without changing Truth Gate, promotion, staking, or OFFICIAL authority.

The public card must remain `NOT Model_P · NOT Truth Gate · NOT OFFICIAL` until this lane has chronological calibration/holdout evidence.
