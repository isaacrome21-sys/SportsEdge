# CFB margin compression: diagnosis, fix, before/after (t272, 2026-10-24)

Status: **SCREEN / NOT_VALIDATED**. Nothing here validates a family, changes
any gate, or authorizes a play. Market prices are used only to score.

## Diagnosis

`FREE_TEAM_SCORE_HEURISTIC_UNVALIDATED` built each CFB team's rating as
`0.12 x mean(last<=5 margins)`, capped at +/-3 points, and added it to that
team's own points with a 2.5-point HFA. Three defects:

1. **Shrinkage/cap (main cause).** Regressing actual 2024 margins on the
   mean-margin difference gives k = 0.532, not 0.12: margins were compressed
   ~4.4x, and the +/-3 cap limited any matchup to ~8.5 points. Every game the
   market had at 11-18 collapsed toward pick'em, so the big underdog always
   "covered" (2025: model sided with the dog in 92.6% of games).
2. **Totals mixed with margin.** Because each rating was added to the team's
   own score, total = 56 + r_home + r_away: margin strength moved the total, and
   the 56-point base sat above typical closing totals (Over side 75.8%).
3. **Sigma.** sd_margin 19.0 / sd_total 18.5 were unfitted; 2024 residual sd is
   16.5 / 16.3. Moneyline vs spread was already internally consistent (same
   normal, Cincinnati +11.5 74% vs ML 52% was consistent with a ~0.4-point
   margin); the margin itself was wrong.

## Fix (CFB only; NFL/NBA/MLB unchanged)

`artifacts/free_models.py` `CFB_MARGIN_MODEL` (version
`CFB_MARGIN_TOTAL_FIT_2024_V1`), fitted on 2024 actual results only:
margin = 4.31 + 0.532 x (mean margin home - mean margin away), rating cap +/-24;
total = 19.37 + 0.6465 x mean(recent game totals of both teams);
sd_margin 16.46, sd_total 16.34. With no scoring-environment history, the
shared composition is used (same margin; league-mean total).

## Data (no credit-consuming collector run)

* Lines: the sha256-pinned free archive in
  `config/research/cfb_historical_market_source_v1.json`
  (sha256 7ae899d9...8d4d verified), median across books per game.
* Results: ESPN public scoreboards (keyless), FBS, 2023-2025.
* Inputs are point-in-time: last <=5 same-season completed games before
  kickoff, >=3 required per team. Neutral sites still get HFA (live model has
  no neutral flag). Pushes excluded.
* Fit 2024, evaluate 2025 (out of sample). Script:
  `scripts/eval_cfb_margin_calibration.py`.

## Before / after

| Metric | 2025 before | 2025 after | 2024 before | 2024 after |
|---|---|---|---|---|
| games | 631 | 631 | 610 | 610 |
| Brier, spread cover (0.25 = coin flip) | 0.2829 | 0.2729 | 0.2807 | 0.265 |
| Brier, total over | 0.2719 | 0.2584 | 0.2622 | 0.2484 |
| Brier, moneyline | 0.2313 | 0.2061 | 0.2314 | 0.209 |
| share of games model sides with spread underdog | 0.9255 | 0.6545 | 0.9115 | 0.6639 |
| share of games model sides Over | 0.7575 | 0.6355 | 0.7443 | 0.6475 |
| spread rows with |p-0.5|>=0.03 | 532 | 538 | 507 | 522 |
|   of those, underdog share | 0.9737 | 0.6914 | 0.9783 | 0.6973 |
|   of those, ATS hit rate | 0.5038 | 0.5093 | 0.499 | 0.5402 |
| total rows with |p-0.5|>=0.03 | 560 | 496 | 537 | 498 |
|   of those, Over share | 0.7821 | 0.6855 | 0.7672 | 0.6747 |
|   of those, hit rate | 0.5411 | 0.5121 | 0.5419 | 0.5582 |
| slope of model margin on closing margin (1.0 = no compression) | 0.133 | 0.618 | 0.129 | 0.621 |
| mean |model margin - closing margin| | 7.77 | 5.43 | 7.87 | 5.75 |

### 2025 spread-cover calibration (home side)

Before:

| bin | n | predicted | actual |
|---|---|---|---|
| 0.0-0.1 | 13 | 0.055 | 0.385 |
| 0.1-0.2 | 32 | 0.147 | 0.438 |
| 0.2-0.3 | 54 | 0.253 | 0.593 |
| 0.3-0.4 | 90 | 0.354 | 0.522 |
| 0.4-0.5 | 158 | 0.456 | 0.475 |
| 0.5-0.6 | 101 | 0.549 | 0.554 |
| 0.6-0.7 | 102 | 0.644 | 0.529 |
| 0.7-0.8 | 53 | 0.745 | 0.528 |
| 0.8-0.9 | 24 | 0.841 | 0.375 |
| 0.9-1.0 | 4 | 0.931 | 0.75 |

After:

| bin | n | predicted | actual |
|---|---|---|---|
| 0.0-0.1 | 5 | 0.056 | 0.2 |
| 0.1-0.2 | 16 | 0.16 | 0.5 |
| 0.2-0.3 | 25 | 0.261 | 0.6 |
| 0.3-0.4 | 81 | 0.359 | 0.556 |
| 0.4-0.5 | 129 | 0.451 | 0.442 |
| 0.5-0.6 | 166 | 0.55 | 0.518 |
| 0.6-0.7 | 142 | 0.644 | 0.556 |
| 0.7-0.8 | 52 | 0.751 | 0.519 |
| 0.8-0.9 | 14 | 0.837 | 0.286 |
| 0.9-1.0 | 1 | 0.931 | 1.0 |

### 2025 moneyline calibration (home win)

Before:

| bin | n | predicted | actual | market no-vig |
|---|---|---|---|---|
| 0.4-0.5 | 55 | 0.477 | 0.327 | 0.217 |
| 0.5-0.6 | 497 | 0.549 | 0.555 | 0.556 |
| 0.6-0.7 | 68 | 0.617 | 0.912 | 0.844 |

After:

| bin | n | predicted | actual | market no-vig |
|---|---|---|---|---|
| 0.0-0.1 | 1 | 0.093 | 0.0 | 0.074 |
| 0.1-0.2 | 13 | 0.143 | 0.385 | 0.13 |
| 0.2-0.3 | 31 | 0.25 | 0.194 | 0.231 |
| 0.3-0.4 | 51 | 0.352 | 0.431 | 0.309 |
| 0.4-0.5 | 100 | 0.453 | 0.4 | 0.443 |
| 0.5-0.6 | 121 | 0.547 | 0.43 | 0.512 |
| 0.6-0.7 | 128 | 0.65 | 0.68 | 0.627 |
| 0.7-0.8 | 93 | 0.745 | 0.742 | 0.709 |
| 0.8-0.9 | 63 | 0.845 | 0.889 | 0.808 |
| 0.9-1.0 | 19 | 0.922 | 1.0 | 0.918 |

## Honest read

The compression is largely fixed (slope 0.13 -> 0.62, dog share 93% -> 65%,
moneyline Brier 0.231 -> 0.206 and well calibrated), but against closing
spreads and totals the model still has **no demonstrated skill**: its cover
Brier remains above 0.25 (worse than a coin flip), the high-confidence cover
bins are overconfident, and residual underdog/Over lean remains. A last-5
raw-margin model with no opponent adjustment cannot beat a closing line.
Treat spread/total "edges" from this model as screen noise, not value.
