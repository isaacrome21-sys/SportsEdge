# NRFI Market Consensus v1

Purpose: use the live betting market as a second pricing model for NRFI/YRFI without allowing sportsbook data to contaminate frozen model-validation or promotion evidence.

## Inputs

Each sportsbook contributes a two-way NRFI/YRFI price at the same capture moment. Both sides are required so hold can be removed. A single sportsbook is never called consensus.

## Processing

1. Convert American odds to implied probabilities.
2. Remove two-way hold proportionally for each book.
3. Weight market makers/sharper books more heavily using explicit weights.
4. Blend the weighted mean with the cross-book median to reduce single-book outlier influence.
5. Record cross-book dispersion.
6. Compare the independent baseball-model probability with the de-vigged market consensus.
7. Compute EV using the actual offered price.
8. Release only when model-vs-market edge, offered-price EV, book count, and market-dispersion gates all pass.

Default release gates are intentionally conservative starting values, not validated promotion thresholds:

- at least 3 books
- model minus market probability edge >= 1.5 percentage points
- EV at the offered price >= 2.0%
- cross-book NRFI probability dispersion <= 4.5 percentage points

These thresholds can be tuned only with separate forward evidence. They do not change V6 gates.

## Movement / steam

Opening and current consensus probabilities may be compared. A move of at least 1 percentage point is classified as NRFI or YRFI steam. Movement is context, not an automatic bet.

## CLV

Every qualifying entry may be written to an append-only JSONL journal with the model probability, consensus probability, offered price, EV, books used and dispersion. A later CLOSE record stores closing consensus and probability-space CLV. Historical ENTRY records are never rewritten.

## Separation from model eligibility

This layer is market-derived and therefore MUST NOT feed frozen baseball model features, model holdout scoring, Brier/log-loss validation, or candidate promotion decisions. Journal records explicitly set `promotion_evidence: false`. Market consensus can gate a tradable release or measure CLV; it cannot make V6 eligible.
