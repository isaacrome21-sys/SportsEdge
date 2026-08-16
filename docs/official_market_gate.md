# SportsEdge OFFICIAL market gate

A market may emit `SPORTSEDGE OFFICIAL` only when all of the following are true:

- canonical quote acquisition is supported and fresh;
- game/player identity is bound to MLB identifiers;
- Model_P is independent of sportsbook prices/probabilities;
- the production feature contract matches the validated artifact contract;
- cutoff-correct validation and calibration evidence exists;
- a frozen non-zero market-specific edge floor exists;
- deployment eligibility is explicitly true for that market/version;
- the individual wager clears edge, EV, freshness, lineup/starter and uncertainty checks;
- the prediction is written to an immutable pregame ledger and later settled.

Acquiring a quote does not authorize a model. Adding a market to the catalog does not authorize a bet. This prevents missing-market engineering work from becoming a backdoor eligibility sweep.
