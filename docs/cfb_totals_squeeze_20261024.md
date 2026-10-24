# CFB totals squeeze diagnosis (2026-10-24)

Status: SCREEN / NOT_VALIDATED, `play_allowed=false`. Research diagnosis only; CFB remains research-only with 0 PLAYs.

## Question
Live CFB cards were reported as "all unders" while the 2023-25 matchup backtest leaned over on 76% of 2025 totals.

## Source (exact)
- Card: box file `/home/box/cfb1024/card_f2.json` (`card.as_of_utc` = `2026-10-24T03:56:43.135875+00:00`; `input_snapshot.n_rows` = 204 input quote rows, `evaluated_rows` = 234 output rows (CFB TOTAL rows are a subset of `evaluated_rows`); produced by the box working copy driven by `cfb1024/run.py`, **not** a committed main SHA).
- No "all unders" CFB card was found in the repo or on the box; none was regenerated (regeneration requires live ESPN fetches).
- Extracted table: `/home/box/cfbeval/totals_audit_card_f2.json` (one row per CFB game with a priced TOTAL row).

## Method
For each CFB TOTAL row in `card.evaluated_rows` with `home_mean`/`away_mean` (first row per game):
- final projection = `home_mean + away_mean`
- injury = `context.home_injury_pts + context.away_injury_pts`; weather = `context.weather_total_adj`
- raw projection = final - injury - weather; gap = final - market line
- OLS slope of final projection on market line; sample SDs.

## Measured results (34 games)
| Measure | Value |
|---|---|
| Games over-lean / under-lean | 24 / 10 |
| Mean gap (final - line) | +2.72 pts |
| Games with nonzero injury adj | 0 (injury source `MISSING_OR_UNRECOGNIZED_SOURCE`) |
| Games with nonzero weather adj | 0 |
| Slope of final projection vs line | 0.403 |
| SD of market lines / projections | 5.73 / 2.96 |
| Crossover line (projection = line) | ~55.3 |
| Projection range / line range | 48.6-60.5 / 40.5-62.5 |

## Conclusion
Projected totals are compressed toward ~55 (they move ~0.40 pt per 1 pt of line). The model therefore says OVER whenever the line is below ~55 and UNDER whenever it is above; a slate of high totals yields "all unders" and a low-total slate yields "all overs". Injury and weather deductions did not cause the lean on this card (both zero). This is a model calibration defect, not an edge.

## Disposition
- `grok/t277`: CFB rows are `WATCH_CFB_MARKET_ONLY_NO_VALIDATED_WEIGHT` (market-only fallback, no model-derived edge) and the 15% blend is retired for CFB.
- Uncalibrated injury/weather adjustments cannot create positive-EV rows (`WATCH_UNVALIDATED_INJURY_WEATHER_ADJ`).
- A CFB totals model may only be promoted after it beats the closing no-vig market out of sample under ruling 2026-10-23i.

## Note: other sports still use the 0.15 anchor
`artifacts/free_models.py` `ANCHOR_WEIGHT = 0.15` (Lane B) remains for non-CFB sports. It is an **unvalidated** research prior kept only because frozen NFL test `tests/test_contract_repairs_20261011.py:150` asserts it. Flagged for retirement after the frozen clock ends; Lane B can never take positive-EV play status (anchored rows are demoted to a WATCH status).
