# CFB opponent-adjusted ratings (t273, 2026-10-24) — SCREEN / NOT_VALIDATED

**Bottom line: it does not beat the closing market out of sample.** Fit on
2024 only, scored on 2025 (917 games with closing lines): spread-cover Brier
0.2497 vs closing no-vig 0.25 (indistinguishable);
total Brier 0.252 vs 0.25 (worse); moneyline Brier
0.1781 vs closing no-vig 0.1693 (worse). Nothing is validated.

## Model

`sportsedge/sports/cfb/opponent_ratings.py`: ridge-regularized points model
(closed-form equivalent of iterated SRS with a ridge pull),
`pts_home = mu + H/2 + off_home - def_away`, `pts_away = mu - H/2 + off_away - def_home`,
neutral sites H = 0. Separate offense and defense (points prevented) ratings,
so margin and total are projected separately. Prior = previous season's final
ratings x rho. Point-in-time: only games before the kickoff's UTC day.
Hyperparameters (2024 margin MSE grid): lambda = 1.0, rho = 1.0.
Engine (`CFB_OPP_MODEL` in `artifacts/free_models.py`): raw ridge margin/total
recalibrated linearly on 2024 (margin 1.04 + 0.91 x raw; total 33.6 + 0.38 x raw).
Live: ratings refit from keyless ESPN scoreboards for the prior and current
season (strictly before the kickoff day); any failure falls back to the t272
composition. Market prices never enter the model; lines are used only to score.

## Data

Pinned free line archive (config/research/cfb_historical_market_source_v1.json,
sha256 verified), median across books; open lines where the archive has them.
ESPN keyless scoreboards (scores) and game summaries (box stats: yards, plays,
turnovers). Scripts in `scripts/cfb_calibration/`.

## Ablation (2025 out of sample; each group kept only if it improves 2024-fit / 2025 Brier)

Calibrated = Lane-A probability shrunk by a slope beta on the standardized gap
to the line, beta fit on 2024 outcomes (beta = 0 means "the line itself").

| Variant | Spread Brier (cal) | Spread Brier (raw) | Total Brier (cal) | Total Brier (raw) | ML Brier | beta spread / total (2024) |
|---|---|---|---|---|---|---|
| pts | 0.2497 | 0.2651 | 0.252 | 0.2604 | 0.1781 | 0.04 / 0.42 |
| pts+eff | 0.2498 | 0.2661 | 0.252 | 0.2603 | 0.1785 | 0.04 / 0.42 |
| pts+eff+pace | 0.2498 | 0.2661 | 0.2539 | 0.2585 | 0.1785 | 0.04 / 0.69 |
| pts+eff+pace+to | 0.2498 | 0.2644 | 0.2539 | 0.2585 | 0.177 | 0.02 / 0.69 |
| pts+eff+pace+to+rest | 0.2498 | 0.2635 | 0.2539 | 0.2585 | 0.1767 | 0.02 / 0.69 |

Market baselines: spread 0.25, total 0.25, ML 0.1693.
Efficiency (yards/play), pace (plays), turnover margin and rest/bye did not
improve spread or total Brier; turnovers + rest improved ML Brier marginally
(0.1781 -> 0.1767), still worse than market. Selected live variant: points only.
**beta_spread = 0.04 on 2024**: the model's disagreement with the spread carries
almost no information about covers.

## Flagged picks (2025, points variant)

* ATS, gap >= 2.5 pts: 330/613 = 0.538 (95% Wilson 0.499–0.577)
* ATS, gap >= 3 pts: 299/559 = 0.535 (95% Wilson 0.493–0.576)
* O/U, gap >= 2.5 pts: 267/525 = 0.509 (95% Wilson 0.466–0.551)
* O/U, gap >= 3 pts: 232/455 = 0.51 (95% Wilson 0.464–0.556)

Break-even at -110 is 52.4%; every interval includes it.

## CLV-style agreement (open -> close, games where the line moved)

* Spread: 438/795 = 0.551 (95% [0.516, 0.585])
* Total: 469/832 = 0.564 (95% [0.53, 0.597])

The model sides with the direction the line later moves slightly more than
chance, but by close the market has absorbed that information.

## Spread-cover calibration, 2025

Calibrated (beta = 0.04):

| bin | n | predicted | actual |
|---|---|---|---|
| 0.4 | 328 | 0.494 | 0.5 |
| 0.5 | 589 | 0.505 | 0.537 |

Raw Lane A (what the engine card shows):

| bin | n | predicted | actual |
|---|---|---|---|
| 0.0 | 10 | 0.076 | 0.5 |
| 0.1 | 24 | 0.158 | 0.5 |
| 0.2 | 54 | 0.252 | 0.463 |
| 0.3 | 76 | 0.354 | 0.513 |
| 0.4 | 164 | 0.457 | 0.506 |
| 0.5 | 316 | 0.55 | 0.528 |
| 0.6 | 192 | 0.644 | 0.557 |
| 0.7 | 67 | 0.741 | 0.493 |
| 0.8 | 13 | 0.845 | 0.692 |
| 0.9 | 1 | 0.915 | 0.0 |

## Not built (honest gaps)

* EPA/success rate/explosiveness/havoc: need play-by-play; CollegeFootballData requires an API key (not on the box). ESPN box stats were used instead.
* Travel/time-zone HFA: not built (no venue coordinates in the evaluation set); neutral sites are 0.
* QB-change flag: Form 2 identity exists only live; no time-correct historical starter data, so it cannot be evaluated.
* Talent composite / returning production: CFBD key required; not used.
* Weather: no keyless archive of forecasts as of kickoff; not used (no hindsight).
* Line movement, public splits, officials: not used.
