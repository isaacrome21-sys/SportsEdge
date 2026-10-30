# NHL rate v1 vs closing lines — 2013-14 to 2019-20 (out of sample)

**Verdict: no NHL market is validated as a bet. `VALIDATED_BET_MARKETS` stays empty and the card shows LEAN at most.**

## Data (free, public GitHub, anonymous clone)

| What | Source | SHA-256 |
|---|---|---|
| Closing ML / PL / total + final scores, 2011-12..2021-22 | `flancast90/sportsbookreview-scraper` `data/nhl_archive_10Y.json` (MIT, commit 1a820e5) | `399b6503…5168` |
| Team shots per game, 2010-11..2019-20 | `ewnike/cost_of_cup` `Kaggle_stats/game_teams_stats.csv` (Kaggle NHL Game Data mirror) | `a80cc282…e918` |
| Team ids | same repo `team_info.csv` | `2488ecd7…af5d` |

Join: season + home + away + k-th meeting, with the final score required to match. Kaggle leaves out the shootout-winner goal, so a tied Kaggle score with +1 to one side also counts as a match. Bets settle on the book's final score, which includes the SO goal as DK does. 10,407 games matched; 86 dropped on score mismatch.

## Method

- Features are season-to-date and strictly prior, with at least 10 prior games for each team: `(GF/g, opp GA/g, SF/(SF+opp SA), rest=1, home)`. This is the same row the card builds.
- Final score = Poisson regulation goals plus one OT/SO goal to a coin-flip winner on ties. This is the card path.
- **A** = frozen card coefficients (`nhl_rate_v1_freeze.json`), unchanged. **B** = the same spec refit walk-forward: train on all prior seasons, test the next.
- Bet rule = the card rule: take a side when EV ≥ 2% at the closing price. The source has only one total price, so totals are graded at -110 both sides.

## Results (test seasons 2013-14..2019-20, regular season)

| Model | Market | Bets | Hit | Breakeven / no-vig | ROI | ROI 95% CI | Brier model | Brier market |
|---|---|---:|---:|---:|---:|---|---:|---:|
| A frozen | ML | 5,350 | 39.6% | 40.1% | −4.3% | [−7.6, −1.1] | 0.2444 | **0.2392** |
| A frozen | Puck line | 4,461 | 62.8% | 62.5% | −3.2% | [−5.5, −1.0] | 0.2270 | **0.2211** |
| A frozen | Total | 4,817 | 51.6% | 52.4% | −1.5% | [−4.2, +1.2] | 0.2531 | **0.2500** |
| B refit | ML | 4,808 | 40.5% | 41.1% | −4.3% | [−7.7, −0.9] | 0.2430 | **0.2392** |
| B refit | Puck line | 3,780 | 59.1% | 58.7% | −2.6% | [−5.4, +0.2] | 0.2248 | **0.2211** |
| B refit | Total | 3,120 | 52.8% | 52.4% | +0.7% | [−2.6, +4.1] | 0.2504 | **0.2500** |

B totals by season (hit / ROI): 13-14 52.5%/+0.3%, 14-15 51.6%/−1.4%, 15-16 55.5%/+6.0%, 16-17 53.2%/+1.5%, 17-18 50.2%/−4.3%, 18-19 52.8%/+0.7%, 19-20 52.5%/+0.3%. One season carries the result, and its Brier is worse than a 50/50 coin.

## Reading

- On every market and both models, the no-vig closing price forecasts better (lower Brier) than the model.
- ML and the frozen-coefficient puck line lose money with the confidence interval entirely below zero.
- The only number above breakeven is the refit's totals (B), at +0.7% with a CI spanning zero. That isn't the card's model, so it doesn't count as validation. A totals-only refit tested on a recent era is the one lead worth following up.
- Caveats: this era (2013-20) scored less than 2024-26, and totals assume -110 pricing. Neither makes the result more favorable to the model.

Pass rule (written before this run): out-of-sample hit above breakeven, ROI > 0, Brier better than the no-vig market, and the frozen card coefficients must pass, not only a refit. **All markets fail.**

`NOT Model_P / NOT Truth Gate / NOT OFFICIAL`
