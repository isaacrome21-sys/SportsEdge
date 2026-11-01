# simple/ — one small line engine

The whole method fits on one page:

1. **Copy the book.** Fit power ratings to DraftKings' own closing lines. That is the book's line-making, reverse-engineered.
2. **Build our own view.** Fit the same ratings to actual results.
3. **Bet only the gaps.** Bet where our view and the book disagree by a set number of points.
4. **One test.** Pick settings on old seasons, then freeze them and run once on newer seasons. Win rate and ROI at the real price. That's it.

Files: `odds.py` (price math), `ratings.py` (the rating solver), `backtest_nfl.py` (NFL test), `backtest_cbb_sbr.py` (CBB close + opener test on the SBR archive), `props_nfl.py` (NFL props pricer).

## Results so far (all research, none verified)
- **NFL sides**, frozen test on 2020–2026: 694 bets, 51.0% ATS, −1.9% ROI. **No edge**: NFL closing lines are already sharp.
- **CBB sides, bet the close** (SBR archive, not DK, all graded at −110), settings picked on 2016–18, frozen, tested once on 2019–20: 3,317 bets, 49.3% ATS, −5.7% ROI. **No edge.**
- **CBB early-line / CLV, bet the opener** (same data and split): 7,999 bets, average CLV +0.25 pts, 52.2% ATS at the opener, −0.4% ROI. Small real line movement our way, not enough to beat −110. Full output: `results/cbb_sbr_2016_2020.txt`.
- **NFL props, own view only** (nflverse stats, train 2018–22, frozen, test 2024–26): model MAE beats a season average in all four markets (e.g. REC_YDS 19.72 vs 20.11), but tails are miscalibrated. No book lines, so no ROI. Full output: `results/props_nfl_test_20261031.json`.

## NFL props: book-line source search (2026-11-01)
Half 1 ("copy the book") needs historical prop lines. Checked: nflverse has none; this repo has none. A web search found one candidate, a Hugging Face sample (`propline/graded-player-props-sample`). It is a sample with unknown coverage, book and license, and the sandbox proxy refuses huggingface.co (HTTP 403), so nothing was fetched or tested. Paid scrapers (Apify etc.) are out of scope without owner approval.
So the props lane stays: own view tested; book half blocked until a forward DK props capture (`player,market,line,over_odds,under_odds` + `captured_at`) is pushed, then `props_nfl.py price` runs on it as paper.

Next: NFL props pricing once a shared DK props capture is pushed where this lane can read it. A follow-up CBB check is the opener signal at real DK opening prices, which needs forward DK CBB opens.

## Paper-bet ledger (every model, every market, every agent)
`simple/ledger.csv` is the one shared log. `python simple/ledger.py add ...` before the game, `grade ...` after, `summary` for ROI + CLV per model/market.
Paper only. Never edit or delete a row; corrections are new rows. A row needs the DK price, capture time and capture source. No price, no row.
