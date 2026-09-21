# NFL RUN IT card — sides and totals

Feed fresh paired sportsbook quotes plus non-certifying probability estimates, or joint-score simulations. Get a short ranked card. Empty is valid.

```text
quotes.json + estimates.json → python -m sportsedge.nfl_run_it → card
```

## Input contract

Each quote side must include:

- `game_id`, `home`, `away`
- `market`, `selection`, and the exact posted `line` when applicable
- `price_american`
- `book`
- `retrieved_at` with timezone

Every quote must have exactly one complementary side from the same book and threshold. One-sided prices are refused; no raw implied probability is treated as market fair probability.

Freshness is fail-closed: quote TTL is 180 seconds, quote clock skew is at most 30 seconds, and the two paired sides must be timestamped within 30 seconds of each other.

The card uses the shared POWER devig implementation (`POWER_V1`). A side above +400 triggers multiplicative/POWER/Shin sensitivity comparison and is blocked when method spread exceeds 1 percentage point.

Probability rows use `estimate_p`, never `model_p`. This card does not certify any estimate as Model_P.

## Push handling

Integer NFL spreads and totals can carry material push mass. A scalar `estimate_p` is not enough for those thresholds, so integer spread/total rows require `--simulations` joint-score paths. Win, push, and loss mass are then used directly in EV.

Non-integer spreads/totals and moneylines may consume `estimate_p` rows. If joint simulations are supplied where no estimate exists, the card may derive the estimate from those paths.

## Card face

The card shows only:

- pick at the exact posted line
- executable price
- estimated edge versus paired POWER no-vig probability
- expected return per dollar

There is no score /100, narrative `why`, or other unfrozen confidence input. Ranking is EV first, then estimated edge, with deterministic identity tie-breaks.

Every card, including an empty card, ends with:

`NOT Model_P / NOT Truth Gate / NOT OFFICIAL`

## Scope

NFL `moneyline`, `spread`, and `total` only. Props remain outside this shape and belong in a separate experimental lane.

This PR does not wire a paid/live Odds API. The intended next intake slice is phone-friendly manual entry (for example, a GitHub issue form) that records both sides plus `retrieved_at` and materializes `quotes.json`.
