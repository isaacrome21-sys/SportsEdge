# TOP_DOWN_MARKET_VALUE_V1

`TOP_DOWN_MARKET_VALUE_V1` is a **research-only PAPER lane** for measuring price dislocations against sharp two-sided markets. It is deliberately separate from the SportsEdge predictive-model lane.

## Non-negotiable separation

The lane may create `market_fair_p`. It must never create, populate, overwrite, infer, or promote `Model_P`.

External products, social accounts, pick records, claimed ROI, claimed CLV, handicapper opinions, consensus picks, and historical screenshots are research context only. They are not model inputs, validation evidence, promotion evidence, or directional votes.

A market-value signal may be displayed beside an independent SportsEdge model signal, including a simple agreement/disagreement flag, but agreement does not increase either probability and cannot bypass either lane's governance.

## Frozen V1 policy

The executable policy is `config/market_value_v1.json`.

- Status: `PAPER`
- De-vig method: Shin
- Minimum market-derived EV: 2.00%
- Executable American-odds range: -400 through +165
- `PINNACLE_ONLY_V1`: Pinnacle two-way price only
- `SHARP_CONSENSUS_V1`: median fair probability from at least two available books among Pinnacle, Circa, and Bookmaker
- OFFICIAL eligibility: false
- External performance claims as validation: false

The loader rejects unknown policy keys rather than silently carrying configuration that code does not consume.

## Market identity and provenance

Every quote requires:

- book
- exact `market_key`
- selection
- American odds
- timezone-aware capture timestamp
- source

Both sides of a reference pair must come from the same book and exact same `market_key`. Cross-line pairing is rejected. Consensus references must also resolve to the same exact market and the same two selections.

A `market_key` must distinguish all terms needed to make the wager identical, such as sport/event, participant where applicable, market type, period, side definition, and line. For a pitcher strikeout prop, `5.5` and `6.5` are different markets and may never be paired.

## Calculation

For each eligible sharp reference book:

1. Convert both posted prices to raw implied probabilities.
2. Remove margin using the frozen Shin method.
3. Produce `market_fair_p` for each side.
4. In consensus mode, take the median fair probability across eligible reference books.
5. Find the best executable price for each side within the frozen odds range.
6. Compute market-derived EV as:

   `EV = market_fair_p * decimal_execution_price - 1`

7. If the larger side's EV is at least 2%, emit `PAPER_BET`; otherwise emit `NO_BET`.

This is a price-comparison signal, not an independently estimated event probability.

## Closing-price record

A qualifying PAPER decision can later receive a separate closing snapshot. The close is append-only and cannot rewrite the original decision, execution price, timestamp, or source.

V1 CLV is represented as the value of the original execution price against the closing sharp-derived fair probability:

`CLV = close_market_fair_p * original_decimal_execution_price - 1`

Positive values mean the original price beat the closing sharp-derived fair benchmark under the same frozen de-vig/reference policy.

## Promotion

V1 contains no promotion path and cannot produce an OFFICIAL wager. Any future promotion policy must be introduced as an explicit governance change after prospective, timestamped, wager-level evidence exists. Evaluation must occur only at predeclared checkpoints; it must not promote the lane because a continuously watched sample happened to cross a favorable threshold.

Claims shown by Sharp Shot Picks, Selene, ThunderBet, EdgeHunterHQ, Olympus, or any similar external product do not count toward that evidence. Their useful role is product/methodology research, price discovery, or source discovery only.

## RUN IT presentation contract

When wired into a card, keep the lanes visually distinct. Example:

```text
MODEL
Model_P 61.8% | Fair -162 | DK -135 | Model EV +8.4%

MARKET
Market_Fair_P 58.9% | Fair -143 | DK -135 | Market EV +2.4%
Reference PINNACLE_ONLY_V1 | Status PAPER

CROSS-LANE
Agreement YES
```

`Agreement` is descriptive only. It is never a confidence boost, vote, or Truth Gate substitute.
