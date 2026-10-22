# NBA Elo sides V2 — date-only historical screen (October 21, 2026)

**Research-only NEGATIVE indicator. NOT a certified historical quote-backtest, not a valid market-vig/CLV replay, and no PLAY or live betting authority.**

## Source and limitations

- Public [SBR historical archive](https://github.com/flancast90/sportsbookreview-scraper/blob/1a820e50c6fbd0276cde073c22bfffae78930868/data/nba_archive_10Y.json), upstream commit `1a820e50c6fbd0276cde073c22bfffae78930868`, path `data/nba_archive_10Y.json`, Git blob SHA1 `f5ba0d4f8f729236fdd8883a65189f2d6443338c`, 7,148,928 bytes.
- 13,903 raw rows, 13,893 normalized rows over seasons 2011–2021. Dates are **calendar dates**, not game instants; no independently attested quote-capture timestamps, result-available timestamps, or book identity. The source field named “close” is an **INDICATIVE archival reference** only. Its mere existence does **not** satisfy SportsEdge historical-source admission rules. No fake clocks were added.
- Research diagnostic uses **STRICTLY PREVIOUS calendar days** to determine the eligible Elo state. Every game's prediction on a particular date is calculated before any score from that date is used in an update; same-date order unknown, all state updates applied only for future dates.
- Elo parameters were **declared and untuned**: K=20, init=1500, scale=400, per-point=20, home court=2 points, year change regression 33% toward 1500, margin-of-victory normalization NBA SD12.5 to NFL SD13.7. A new team must have 5 previous-date games. 2011–14 warmup, 2015–2021 holdout. No market prices enter model state.
- Followed `sportsedge/ratings/elo.py` pre-rating, season-regression and MOV arithmetic; read `rating_at` does not season-regress until a result is recorded. This is deliberate, not evidence of correct early-season calibration.

## Exploratory executed result

The following exploratory calculation was performed over the actual public source retrieved through GitHub, with independent implementation of the declared arithmetic. An **independent rerun of the committed Python CLI is still required** to verify all numerical values; do not cite these as independent reviewer-certified output.

| Metric (lower is better) | Research V2 | Indicative archived market | Matched games |
|---|---:|---:|---:|
| Full-game margin RMSE | **13.4522** | **12.7511** | 8,215 |
| Home moneyline Brier | **0.21755** | **0.20670** | 8,877 |

Also: 8,877 model-scored holdout fixtures; total model margin RMSE 13.49755 over those 8,877. Archived-spread comparisons span 1,417 distinct calendar dates; ML comparisons 1,429 dates. Paired candidate minus indicative market margin MSE **+18.36965** points²; paired candidate minus market Brier **+0.0108551**. On this source/cohort the challenger does **not** beat the market reference, even ignoring missing timestamp authenticity.

## Reproduction path

```bash
python scripts/research_nba_elo_sbr_dateonly_screen.py \
  --source /path/to/unaltered/nba_archive_10Y.json \
  --output /path/to/elo_dateonly_report.json
```

The CLI checks the exact original Git-blob digest before any scoring, uses deterministic date ordering, refuses duplicate fixtures/invalid dates, and emits the data-quality caveats explicitly. It does **not** retrieve outside data or modify any forward ledger. For a full independent audit, verify SHA-1, source coverage, head SHA, CI, and programmatic output. Compare reproducible metrics above; investigate any difference rather than assuming equivalence.

## Decision

**HOLD AS RESEARCH ONLY — NO MODEL PROMOTION.** The documented old V1 game-side validation failure remains; this challenger does not overcome the indicative reference on the tested holdout. Improving a model or removing all-UNDER visual bias is not a substitute for evidence of market advantage. It must never receive official Model_P, market edge, ranking 99, or a prospective freeze based on this preliminary date-only screen. No historical rows may be retroactively added to the NBA props/forward clock. Any future legitimately time-stamped market archive, preregistration and independent calibrated test constitute a separate workstream.
