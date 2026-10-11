# NFL moneyline devig method backtest — pre-registration

**Status:** frozen before any results are computed.
**Scope:** fair-price check only. No model, Attempt 9, or M2 changes.

## Data
- Source: nflverse `games.csv` (`away_moneyline`, `home_moneyline`, scores).
- Drop any game missing either closing moneyline or either final score.
- Drop ties entirely (two-way moneyline does not cover a tie). No imputation.

## Methods
1. Multiplicative (current production): raw implied / sum.
2. Power: solve `q_a^k + q_b^k = 1`, then use `q^k`.
3. Shin: insider-parameter bisection.

All three are already implemented in `sportsedge/devig.py` and `sportsedge/sports/nfl/fair_odds.py`.

## Split
- Selection set: seasons ≤ 2022 (or earlier years with complete data).
- Holdout: seasons ≥ 2023.
- Report log loss per season on the holdout, plus pooled.

## Decision rule
- Switch production fair-price check only if one method has lower log loss than multiplicative in most held-out seasons.
- Near-tie or mixed results → keep multiplicative.
- No other changes.

## Pass bar
None. This is a method selection for the fair-price check, not a betting market promotion.
