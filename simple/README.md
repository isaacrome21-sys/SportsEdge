# simple/ — one small line engine

The whole method fits on one page:

1. **Copy the book.** Fit power ratings to DraftKings' own closing lines. That is the book's line-making, reverse-engineered.
2. **Build our own view.** Fit the same ratings to actual results.
3. **Bet only the gaps.** Bet where our view and the book disagree by a set number of points.
4. **One test.** Pick settings on old seasons, then freeze them and run once on newer seasons. Win rate and ROI at the real price. That's it.

Files: `odds.py` (price math), `ratings.py` (the rating solver), `backtest_nfl.py` (NFL test).

## Result so far
NFL sides, frozen test on 2020–2026: 694 bets, 51.0% ATS, −1.9% ROI. **No edge**: NFL closing lines are already sharp.
Next: run the same engine on college basketball (CBB), where books have to price 360+ teams.

## Paper-bet ledger (every model, every market, every agent)
`simple/ledger.csv` is the one shared log. `python simple/ledger.py add ...` before the game, `grade ...` after, `summary` for ROI + CLV per model/market.
Paper only. Never edit or delete a row; corrections are new rows. A row needs the DK price, capture time and capture source. No price, no row.
