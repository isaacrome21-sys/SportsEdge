# Open-source betting repo integration review — 2026-08-12

Purpose: extract production patterns that improve SportsEdge automation without importing unvalidated model probabilities, changing frozen model math/tolerances, or weakening the Truth Gate.

## Accepted now

1. **Durable decision ledger / settlement-ready event history**
   - Inspired by production betting-bot patterns that persist analyzed offers and later reconcile them.
   - SportsEdge records every analyzed candidate, including BLOCKED and PASS rows, not just official bets.
   - Each decision receives a deterministic identity scoped to the automation run and exact offer identity.
   - Provider status/provenance is copied into the ledger for later audit, CLV, settlement, and source reliability analysis.
   - This layer is strictly observational and cannot alter Model_P or bet_status.

2. **Persistent run history across scheduled automation**
   - The 15-minute MLB workflow restores and saves a same-day decision-history cache.
   - This creates the join key needed for future closing-line capture, settlement, bankroll reconciliation, duplicate-action prevention, and performance reporting.

## Already present in SportsEdge and therefore not imported

- Fractional Kelly sizing.
- EV/edge evaluation and bettor-facing fair-price display.
- Fail-closed quote freshness and double-TTL checks.
- Walk-forward / cutoff-correct validation discipline.
- Source provenance, exact artifact hashes, deployment eligibility registry, and Truth Gate.
- Full-slate accounting and immutable last-valid-pregame evidence.
- MLB-native projected lineups and live probable-pitcher gating.
- Sportsbook-independent Model_P for deployed MLB game markets.

## Deferred until independently validated

- Third-party MLB model probabilities, XGBoost veto layers, neural-network predictions, Elo blends, or market-consensus blends.
- Pinnacle/other sharp-book probabilities as model features. They may become price-comparison or market-benchmark evidence, but never silently enter Model_P.
- Generalized Kelly across correlated simultaneous outcomes. SportsEdge should add portfolio-aware exposure only after explicit correlation/portfolio tests.
- Automated bet placement. Placement requires a separately audited adapter with idempotency, exact-offer binding, max exposure, stale-price rejection at click/submit time, and jurisdiction/book terms compliance.
- Automatic model retraining from fresh results. Frozen production models stay frozen until a predeclared rebuild/validation protocol passes.

## Rejected

- Copying star-ranked repositories wholesale.
- Treating reported ROI/accuracy in a repository README as deployment evidence.
- Browser automation that bypasses sportsbook restrictions or source terms.
- Any implementation that substitutes sportsbook implied probability for SportsEdge Model_P.

## Next automation milestones

1. Closing-line snapshot capture keyed by decision_id.
2. Result settlement keyed by game/player/market identity.
3. Bankroll and exposure journal with idempotent official-bet reservation/release.
4. Duplicate-bet prevention across the 15-minute polling loop.
5. Placement adapter only after all four above are proven fail-closed in shadow mode.
