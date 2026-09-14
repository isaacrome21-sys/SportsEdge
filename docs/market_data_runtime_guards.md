# Market-data runtime guards

This layer is deliberately fail-closed.

- Pregame sportsbook quotes may bind prices only after an independently authorized SportsEdge Model_P exists.
- Live quotes are collection/research context only and return `NO_ENGINE`, `PAPER`, and `0.0` units until a separately validated live engine is introduced.
- Model_P authority and staking authority are separate. Model_P without staking authority remains `PAPER` with `0.0` units.
- Public ticket/handle splits from Action Network, ScoresAndOdds, Covers, or similar pages are `SINGLE_SOURCE_UNVERIFIED`, methodology-undisclosed context. They are never Model_P, Truth Gate, promotion, or confidence-vote inputs.
- Scrape failure/layout drift must be represented explicitly and must never be interpreted as an empty/no-divergence signal.
- Provider authentication failures are machine-readable. Request URLs are redacted before being included in errors so API keys/tokens are not exposed.
- Historical odds are not evidence merely because they are available. Admission still requires exact timestamp, book, event, paired-market semantics, raw-byte hash, and PIT checks under the separate historical-price admission contract.
