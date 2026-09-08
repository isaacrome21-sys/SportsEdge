# Decision-policy validation boundary

SportsEdge separates probability-model validation from decision-policy validation.

A decision policy that operates on sportsbook prices, cross-book discrepancies, line shopping, arbitrage, CLV targeting, or similar market structure does not become a probability model merely because it selects wagers.

Therefore:

- Brier score, log loss, calibration slope/intercept, ECE, and other proper scoring rules validate probability estimates only.
- CLV, realized ROI, after-vig ROI, turnover, drawdown, and policy-specific selection metrics validate decision policies.
- A market-scanning or +EV/arb policy must maintain an independent immutable ledger of decisions, timestamps, source identities, prices, closes, and outcomes.
- Policy output may not be labeled Model_P unless it was produced by a separately governed probability model.
- Policy performance may not be used to manufacture model calibration evidence.
- Capper or social output may be retained as commentary only and may not vote on Model_P, promotion, or confidence.

This boundary applies to any future arb, line-shopping, sharp-reference, or CLV scanner added to SportsEdge.
