# NFL CLV Promotion Evidence Contract

SportsEdge promotes NFL markets on **no-vig probability CLV**, not raw line movement:

```text
CLV = closing_no_vig_probability(side at decision threshold)
    - decision_no_vig_probability(side at decision threshold)
```

Promotion-grade observations must also prove that the close was captured **after the decision, before game start, and at the same sportsbook**.

## Why the threshold must be fixed

A spread or total can move while the price remains unchanged. For example, a team may move from -3 (-110) to -3.5 (-110). The no-vig probability of the quoted side at each market's own current threshold can be about 0.50 in both snapshots, even though the market moved materially.

Those two probabilities describe different events:

- cover -3
- cover -3.5

Subtracting them is not valid CLV evidence.

## Required decision record

Promotion evidence requires at least:

```text
decision_ts, game_start_ts,
game_id, market, side, book,
line_at_decision, price_at_decision,
model_prob, novig_prob, ev, kelly_frac, stake_units, gate_result,
model_id, feature_contract, code_git_sha
```

`decision_ts` and `game_start_ts` must be timezone-aware and `decision_ts < game_start_ts`.

## Required close record

```text
close_ts, game_start_ts,
game_id, market, side, book,
closing_line, closing_price,
closing_novig_prob, probability_line,
model_id, feature_contract, code_git_sha
```

The close must reproduce the decision's game/market/side/book identity, exact production code identity, and exact game-start timestamp. It must satisfy:

```text
decision_ts < close_ts < game_start_ts
```

A close from another sportsbook cannot score the decision.

## Moved-line example

If the market closed -3.5 but the decision was -3, promotion-grade probability CLV requires a closing alternate quote at the original -3 threshold:

```text
line_at_decision = -3.0
closing_line = -3.5
probability_line = -3.0
closing_novig_prob = no-vig P(cover -3) at close
```

`probability_line` must equal `line_at_decision`.

For backward-compatible same-line core replays, `probability_line` may be omitted only when `closing_line == line_at_decision`. The NFL promotion builder still requires the full forward-time and book identity contract.

Line-free markets such as moneyline have no threshold and must not provide `probability_line`.

## Sample-count integrity

A `game_id / market / side` observation counts once for NFL promotion. The same model play repeated at several books cannot be multiplied into several CLV observations merely to increase `n`.

## Fail-closed rules

Examples include:

```text
CLV_REFERENCE_LINE_MISMATCH
NFL_CLV_CLOSE_NOT_AFTER_DECISION
NFL_CLV_CLOSE_NOT_PREGAME
NFL_CLV_CLOSE_BOOK_MISMATCH
NFL_CLV_GAME_START_MISMATCH
NFL_CLV_DUPLICATE_OBSERVATION
```

Do not replace missing comparable probability with raw line delta, a probability at the new threshold, an inferred conversion, another book's close, or a post-start quote.

## Promotion binding

NFL promotion accepts only CLV evidence with:

```text
schema_version = 4
clv_probability_reference = "DECISION_THRESHOLD"
forward_time_contract = "PREGAME_DECISION_TO_PREGAME_CLOSE"
close_book_contract = "SAME_BOOK_AS_DECISION"
```

The CLV evidence must also match the exact production model ID, feature contract, and code Git SHA used by the math and historical evidence. A code change resets the forward CLV evidence identity.
