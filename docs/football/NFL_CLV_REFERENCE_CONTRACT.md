# NFL CLV Probability Reference Contract

SportsEdge promotes NFL markets on **no-vig probability CLV**, not raw line movement:

```text
CLV = closing_no_vig_probability(side at decision threshold)
    - decision_no_vig_probability(side at decision threshold)
```

## Why the threshold must be fixed

A spread or total can move while the price remains unchanged. For example, a team may move from -3 (-110) to -3.5 (-110). The no-vig probability of the quoted side at each market's own current threshold can be about 0.50 in both snapshots, even though the market moved materially.

Those two probabilities describe **different events**:

- cover -3
- cover -3.5

Subtracting them is not valid CLV evidence.

## Required close record

For a line market, the close record must identify the threshold at which `closing_novig_prob` was measured.

```text
game_id, market, side,
closing_line, closing_price,
closing_novig_prob, probability_line
```

If the market closed -3.5 but the decision was -3, promotion-grade probability CLV requires a closing alternate quote at the original -3 threshold:

```text
line_at_decision = -3.0
closing_line = -3.5
probability_line = -3.0
closing_novig_prob = no-vig P(cover -3) at close
```

`probability_line` must equal `line_at_decision`.

For backward-compatible same-line records, `probability_line` may be omitted only when `closing_line == line_at_decision`.

Line-free markets such as moneyline have no threshold and must not provide `probability_line`.

## Fail-closed rule

If a spread/total moved and no closing probability at the original decision threshold is available, the row is **not scored** for promotion and fails with:

```text
CLV_REFERENCE_LINE_MISMATCH
```

Do not replace the missing comparable probability with raw line delta, a probability at the new threshold, or an inferred conversion.

## Promotion binding

NFL promotion accepts only CLV evidence with:

```text
schema_version = 3
clv_probability_reference = "DECISION_THRESHOLD"
```

The CLV evidence must also match the exact production model ID, feature contract, and code Git SHA used by the math and historical evidence. A code change resets the forward CLV evidence identity.
