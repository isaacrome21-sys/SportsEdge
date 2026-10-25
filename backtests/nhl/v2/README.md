# NHL v2 matchup challenger backtest (#2447)

**Historical only.** No production model, threshold, promotion, workflow or the Oct 8 – Nov 30 2026 window is touched. Challenger: `sportsedge/research/nhl_v2_matchup_challenger.py` (imported by nothing in production).

## Data (all free, fetched with git)
- Odds/outcomes: `flancast90/sportsbookreview-scraper@1a820e50` `data/nhl_archive_10Y.json` (blob verified), same as PR #2599.
- Play-by-play: `sportsdataverse/fastRhockey-data` `nhl/json/<gameid>.json`, reduced by `extract_pbp.py` to shots (distance, angle, type, strength, goalie in net), time on ice by manpower state, and **starting goalies**.
- Coverage (regular season): 2011 1230, 2012 720, 2013 1230, 2014 1230, 2015 1229, 2016 1230, 2017 1271, 2018 1271, **2019 908 (174 source files are empty stubs)**, 2020 868, 2021 1312.
- Not available free: point-in-time **injury** reports (omitted). Pre-game *expected* goalie reports are not archived; the actual starter is used as the proxy for a confirmed starter (confirmed starters are normally public before puck drop, but this is a known optimistic assumption).

## Inputs (unit vs unit, point-in-time)
5v5 xGF/60 × opponent 5v5 xGA/60; PP xG/min × opponent PK xGA/min × expected PP minutes; opposing starter goals saved above expected per xG (shrunk); rest, back-to-back, travel km; home ice. xG model refit each season on prior seasons' shots only. Attempts 5–6 add the **opening** line only (never the close).

## Protocol
Dev 2012–2019 walk-forward by season (2011 warm-up); validation 2020-21 picks one attempt (rule declared in code: lowest mean validation log-loss gap to close); 2021-22 locked test scored **once** with the chosen attempt. Leakage check: a day's games are featurized before any of that day's results enter state; 0 violations.

## Attempt log (Brier model − close no-vig; positive = worse than close)
| # | Change | Dev ML | Dev Tot | Dev PL | Val ML | Val Tot | Val PL |
|---|---|---:|---:|---:|---:|---:|---:|
| 1 | 5v5 xG matchup + PP/PK matchup + rest/b2b/travel + home; no goalie | +0.0041 | +0.0041 | +0.0043 | +0.0126 | +0.0072 | +0.0093 |
| 2 | attempt 1 + opposing starter GSAx/xG (shrunk, k=60 xG) | +0.0036 | +0.0033 | +0.0036 | +0.0122 | +0.0061 | +0.0089 |
| 3 | attempt 2 + shrunk GF x opp GA (finishing/results) | +0.0018 | +0.0015 | +0.0021 | +0.0055 | +0.0048 | +0.0045 |
| 4 | attempt 2 + regulation-tie inflation (fit on train) | +0.0037 | +0.0031 | +0.0061 | +0.0126 | +0.0060 | +0.0131 |
| 5 | attempt 4 + OPENING-line anchor (no-vig ML logit, open total) | +0.0007 | +0.0017 | +0.0023 | +0.0039 | +0.0033 | +0.0051 |
| 6 | attempt 5 with slower team decay and stronger goalie shrinkage | +0.0008 | +0.0018 | +0.0024 | +0.0039 | +0.0029 | +0.0049 |

Chosen: attempt **6**. 6 of 8 allowed attempts used.

## Locked test 2021-22 (one evaluation)
| Market | n | Brier model / close | LogLoss model / close | Calib slope / ECE | EV≥2% bets | ROI | mean CLV | Verdict |
|---|---:|---|---|---|---:|---:|---:|---|
| moneyline | 1312 | 0.2286 / 0.2252 | 0.6496 / 0.6421 | 1.48 / 0.041 | 466 | -3.3% | +0.0078 | LOSES_TO_CLOSE |
| totals | 1253 | 0.2537 / 0.2488 | 0.7005 / 0.6907 | 0.50 / 0.071 | 618 | -5.4% | +0.0071 | LOSES_TO_CLOSE |
| puck_line | 1310 | 0.2445 / 0.2365 | 0.6838 / 0.6655 | 0.55 / 0.084 | 1249 | -4.0% | n/a | LOSES_TO_CLOSE |

## Post-test finding (disclosed, test NOT re-run)
After the single locked test, I found that the SBR archive gives 2020-21 games played Jan–Mar 2021 the year 2020. So validation matched only 318 of 868 games, and those same mis-dated rows can overwrite a few 2019-20 dev rows that share a date and home team. With `--fix-2020-dates`, validation covers 864 games and **attempt 5 would have been chosen (0.00716 vs 0.00721)** over attempt 6. Attempts 5 and 6 differ only in decay and shrinkage, and every attempt still loses to the close on the corrected validation (Brier gap ML +0.0026, Tot +0.0030, PL +0.0041 for attempt 5). To keep the test locked, 2021-22 was not re-scored. The 2021-22 odds join is complete (1312/1312).

## Read
Matchup inputs help relative to each other (goalie quality and finishing/market anchor shrink the gap), but no attempt beats the closing no-vig line in any market on dev, validation or test. Totals and puck-line are over-confident (calibration slope ≈0.5). Verdict: **LOSES_TO_CLOSE in all three markets; do not promote.** Caveats as in #2599: totals price is one-sided (4.5% overround assumed), puck line close-only, book unknown, calendar-date clock.

Rerun: `python backtests/nhl/v2/extract_pbp.py <dir of game jsons> games_<yr>.jsonl` per season, then `python backtests/nhl/v2/backtest_nhl_v2.py --odds nhl_archive_10Y.json --pbp <dir with games_*.jsonl>`. `results.json` is a slimmed summary (per-market Brier, log-loss, calibration, bets, ROI, CLV, verdict) of the locked run.
