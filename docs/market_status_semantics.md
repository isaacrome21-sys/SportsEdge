# Market status semantics

SportsEdge reports market state in separate dimensions:

- `ACQUISITION_SUPPORTED`: provider quote can be normalized and identity-bound.
- `MODEL_AVAILABLE`: an independent SportsEdge probability model exists.
- `MODEL_VALIDATED`: the model has passed its declared cutoff-correct evaluation gates.
- `DEPLOYMENT_ELIGIBLE`: the exact artifact/version may run in production.
- `BET_QUALIFIED`: the current fresh quote clears the frozen market-specific Truth Gate.

Only `DEPLOYMENT_ELIGIBLE && BET_QUALIFIED` may render `SPORTSEDGE OFFICIAL`.

This prevents two opposite failures: silently dropping markets merely because they are not modeled yet, and falsely calling a quote official merely because it was acquired.
