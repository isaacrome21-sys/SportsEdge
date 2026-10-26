# NBA sides/totals successor — research construction protocol (2026-10-26)

**Status:** DESIGN ONLY; NO VIABLE CONSTRUCTION YET; not a freeze, forecast, card, or promotion. The earlier SBR date-only screens were negative: sides spread RMSE 13.452 > indicative 12.751; moneyline Brier 0.21755 > 0.20670; totals RMSE 18.977 > 18.051. Do not resurrect those failed constructions.

## Hypothesis and scope
Test whether a new possession-level distribution model with pregame-only pace, lineup availability, rest, travel and opponent-strength inputs improves calibrated side and total probabilities against a **timestamp-authenticated** bookmaker baseline. No same-day final, postgame box score, or untimestamped close may enter features. Separate spreads, moneylines and full-game totals by canonical game/market/line/side.

## Data and leakage gates
Immutable source bytes, provider, captured_at UTC, event tip UTC, book identity, market line and both prices. Join by canonical game ID; record exclusions, missingness, duplicated quotes, moved lines and provider outages. Chronological train/validation/test split by tip, purged windows around revisions, fit transforms only on training folds. Injury/lineup snapshots must predate prediction. Never infer a missing capture timestamp.

## Design / screen / freeze / forward verdict
1. Preregister feature set, fitting code, seed, exact data hashes, exclusions, metrics and frozen holdout BEFORE screening.
2. Compare proper scoring (Brier/log loss), spread/total calibration, held-out RMSE and matched-quote no-vig baselines with uncertainty and subgroup drift. Include ablations and negative controls.
3. **NO VIABLE CONSTRUCTION** if no robust held-out improvement or admitted historical market evidence. Do not optimize on final test fold or replace a failed construction by renaming it.
4. Only if viable: independent exact-head review, pinned artifact and first future counted slate, then forward-only captured entry and genuine timestamped close receipts.
5. Verification requires >=50 graded forward picks, verified CLV >0 and ROI >0. All research outputs PAPER/0u; assumed -110 ROI and untimestamped vs-close are not verified CLV.

## Runtime dependency
P0 DK browser delivery must meet the unchanged capture window with actual per-fixture queue/return/write timestamps and paired receipts before any forward clock is credited.
