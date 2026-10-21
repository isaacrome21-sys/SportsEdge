# NBA scoring-level V2 — exploratory historical date-only screen (2026-10-21)

**Research diagnostic, NOT validation, NOT a certified beat-the-close test, NOT a forward entry.**

## Identified archive and reproducibility

- Public archive: [flancast90/sportsbookreview-scraper, `data/nba_archive_10Y.json`](https://github.com/flancast90/sportsbookreview-scraper/blob/1a820e50c6fbd0276cde073c22bfffae78930868/data/nba_archive_10Y.json).
- Source commit **`1a820e50c6fbd0276cde073c22bfffae78930868`**; Git blob **`f5ba0d4f8f729236fdd8883a65189f2d6443338c`**, reported raw size **7,148,928 bytes**.
- The archive offers **calendar game dates**, final scores, named `close_over_under`, `home_close_spread`, and moneylines, **but no timestamped pregame quote capture, event tipoff or result-available clocks**. Its label `close` does not certify the quote's pre-tip presence or bookmaker identity. It cannot be admitted as actual independent close evidence without a source/governance protocol.
- Read-only reproducibility runner: `python scripts/research_nba_v2_sbr_dateonly_screen.py --source /path/to/unaltered/nba_archive_10Y.json --output /path/to/report.json`. It refuses raw files whose **Git blob SHA-1** differs. It never downloads provider data, touches `data/`, changes admission status, or appends a prospective entry.
- The following computation was directly executed over the public commit contents with the declared V2 arithmetic and is submitted for *independent* reproduction through the command above. It is not an independently verified hosted run of that command.

## Construction and temporal compromise

Research model from #2462: for each game, use the most recent **450 completed games on strictly earlier calendar dates**, preserving multi-season continuity; require >=30 prior league games and >=5 for each team. The league level is the recent mean **points per team**. Home and away projections add each side's shrunk offense and the opponent's shrunk conceded-points offset. Shrinkage `n/(n+20)`. The reference climatology is twice the same league mean. These are previously declared unfitted constants, not optimized on holdout.

Archive calendar dates cannot tell whether an earlier day's final was actually available at a specific later tip, so this **conservative calendar-date approximation** is still not a certified point-in-time replay. Same-day finals never become priors. The market column is observational and *unverified vintage*.

Screen years: **2015–2021** (as the older SportsEdge NBA rating screen used for holdout). Full archive comprises **13,903 raw records**; **13,893 normalized** across source seasons 2011–2021. Different team aliases are normalized consistently with `scripts/backtest_nba_ratings_vs_lines.py`.

## Accuracy (lower RMSE is better)

| Measure | Count | RMSE |
|---|---:|---:|
| New V2 totals forecast, all eligible games | 8,877 | **18.9435** |
| PIT-date climatology, all eligible games | 8,877 | **19.9734** |
| New V2 forecast, *matched* to available archived total | 8,215 | **18.9770** |
| Climatology, same matched reference games | 8,215 | **20.0097** |
| Indicative archive total, same matched games | 8,215 | **18.0512** |

The paired model-minus-market **mean squared error difference is +34.2796 points²** over 8,215 games on 1,417 calendar dates. Exploratory 750-replicate bootstrap resampling dates, with deterministic seed 17, gave a 95% quantile interval **[+29.59, +38.97] points²**. This is *not* an independent formal confidence interval under an authenticated/registered archive, but confirms a material negative difference on this exact observational cohort.

Model total was **below** the archive total in **4,306** pairs and **above** in **3,909** (0 exact ties); this challenger is not structurally all-UNDER on this historical dataset. That does **not** repair the October 21 failed-V1 card.

## Disposition

**KEEP RESEARCH-ONLY; NOT A MARKET BEATER on the examined indicative cohort.** Improving on naive climatology does not satisfy the market benchmark. Do not show these as 99-rated picks, edges, Model_P, official research promotions, or calibrated fair odds. Do not turn the archive's unlabeled timing into fabricated capture timestamps. This report neither changes nor replaces frozen NBA V1 game/prop forward-test rules; no actual historical results are backfilled into a forward clock. Further challenger work requires an independently established event/quote-time archive or an explicitly approved date-level research protocol, new preregistration, and independently reproduced adversarial screen.

## Verification tasks for reviewer

1. Confirm source file raw Git blob at pinned commit and run the new CLI with that unmodified input; compare counts and paired RMSE/MSE metrics.
2. Check strict prior-calendar-day exclusion and no intra-day accidental ingestion (tests include an invalid-date fail and same-date fixture control).
3. Confirm there are no edits to frozen registry, live pricing, odds capture, prospective ledgers or other model parameters.
4. Do not infer book accuracy beyond the unlabeled market-reference field; if a truly admitted same-game paired close exists, run a *separate* model screen with independent governance.
