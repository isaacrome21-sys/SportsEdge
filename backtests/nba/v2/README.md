# NBA v2 matchup challenger (#2447): result is LOSES_TO_CLOSE on all three markets

Research only. `sportsedge/nba_v2_matchup_challenger.py` is not imported by production. No thresholds, promotion or workflows changed.

**Inputs (point-in-time):** these are matchup inputs, not one team-strength number. Each team's offense is rated against the other team's defense in points per 100 possessions (weighted toward recent games, shrunk toward league average, adjusted for opponent). The two teams' paces are combined for expected possessions. Also used: rest, back-to-back, 3-in-4 and travel km from arena coordinates. Player availability counts missing rotation players, weighted by expected minutes and a shrunk on/off plus-minus. Home court is the intercept.
**Player data:** free, cloned with git: NocturneBear/NBA-Data-2010-2024 @ `a5f108b5`. Availability uses only codes that are known before tip-off. DND means the player was on the inactive list. NWT means not with team. A player also counts as out if he played in the last 21 days and is missing from the box. DNP-coach and in-game injuries count as available. This is a stand-in for the pregame injury report, not a timestamped feed. 98.7% of SBR games joined.
**Odds/scores:** SBR archive, blob `f5ba0d4f…`. Spread and total prices are assumed at −110.

**Protocol:** dev window 2011–19 seasons, refit walk-forward each season. 2020-21 was the validation season used to choose. 2021-22 was the final test, run once (`final_test.json`; the script refuses to rerun it). Leakage check: 0 rating inputs dated on or after game day. A same-day outcome scramble on 44 games changed 0 features.

## Attempts (5 of 8 max), validation log-loss gap (model − close; lower is better)
| id | ML | spread | total |
|---|---|---|---|
| A1 matchup only | +.0223 | +.0325 | +.0189 |
| A2 + rest/travel | +.0210 | +.0331 | +.0191 |
| A3 + availability | +.0145 | +.0286 | +.0188 |
| **A4 A3 + opening line as input (chosen)** | +.0002 | +.0067 | +.0097 |
| A5 A4 + ridge 200 | +.0009 | +.0069 | +.0099 |

## Final test 2021-22 (A4, run once)
| Market | n | Brier model / close | LogLoss model / close | Cal slope | EV≥2% bets | ROI | Verdict |
|---|---:|---|---|---:|---:|---:|---|
| Moneyline | 1140 | 0.2093 / 0.2079 | 0.6064 / 0.6028 | 1.07 | 665 | +2.8% (at close) | LOSES_TO_CLOSE |
| Spread | 1014 | 0.2529 / 0.2500 | 0.6991 / 0.6931 | −0.06 | 158 | +19.1% (−110 assumed) | LOSES_TO_CLOSE |
| Total | 1017 | 0.2580 / 0.2500 | 0.7095 / 0.6931 | −0.27 | 65 | −0.1% (−110 assumed) | LOSES_TO_CLOSE |

The positive ROI on moneyline and spread comes from a small sample, and the model loses to the close on both Brier score and log-loss. It is not an edge. The spread ROI comes from bets placed against the opening line, which then tended to move toward the bet (mean CLV +0.06 in win probability, assumed −110). Availability was the input that helped most (A2→A3). Rest and travel added almost nothing. Without the opening line, no attempt came close to the market.

Rerun: `python backtests/nba/v2/backtest_nba_v2.py --source <nba_archive_10Y.json> --box-dir <NBA-Data-2010-2024 clone> --attempt A1_matchup`
