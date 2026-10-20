# MLB props benchmark v1 (research only)

**Question:** do DraftKings MLB prop prices that beat a sharp-book fair price win money? No model is involved; the sharp book is the benchmark.

**Fixed before any real-sample scoring (Oct 19, 2026):** sharp priority list (pinnacle, circa, novig, prophetx, sporttrade, bookmaker); sharp fair = de-vigged two-way price from the first sharp book quoting both sides at the same line, using only quotes at or before the DK quote time; DK entry = DK's last pre-start quote per selection; edge thresholds 0, 2%, 5%; flat 1-unit P&L on the settled outcome; date-clustered bootstrap (seed 20261017, 2,000 resamples); verdict floor 200 bets and 10 date clusters (`common.py`, same helpers as the NBA record, blob 5c0212e5). `bench_mlb_props.py` blob 5812b904.

**Known limit of v1:** the DK entry is DK's last pre-start quote, so entry and close are close in time and the CLV figure is near the entry edge. A v2 should fix an entry time (for example 3 hours before start) in a new prereg before it is run.

**Smoke run on the capped Oct 18 artifact** (`mlb_props_targets.csv.gz`, zip sha256 853e6b9d…6add0e1, 200,000 rows, 4 games): 66 DK quotes had a sharp pair, from 2 games / 2 dates. All thresholds: n = 3 to 9, **INSUFFICIENT_DATA**. This run checks that the script works; it is not a result.

**Next:** run on the uncapped download (max_rows=0). Nothing here is a play.
