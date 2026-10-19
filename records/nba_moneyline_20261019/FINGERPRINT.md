# NBA moneyline record — fingerprint and reproduction notes

## What this folder is

- `bt_nba_lines.py`: the Oct 18 sweep script, byte-identical to the run that wrote `nba_lines_results.json`.
- `common.py`: the helper it imports, byte-identical.
- `nba_lines_results.json`: the results of that run (byte-identical, blob `808977b0`).
- This file: the fingerprint of the input database. The database itself is not in the repo.

## Result (moneyline, model vs de-vigged market, 2022-23..2025-26)

- Brier diff (model − market): **+0.011663853285138217**, cluster-bootstrap CI **[+0.008653, +0.014651]**
- n = 4,374 games, 666 date clusters, seed 20261017, 2,000 resamples.
- Subset: games where the spread favorite and the moneyline favorite agree (`ml_fav_home == (spread > 0)`), spread = 0 counted as agreeing.
- Reproduced exactly on Oct 19 by re-running the preserved script against the preserved database. The rerun printed the same digits.

## What the price is, and what it is not

- Prices come from `ML_Home` / `ML_Away` in `OddsData.sqlite`, de-vigged two-way.
- The database has **no timestamps**. Closing versus opening is **not established**. Under the acceptance bar, these are lines of unknown vintage.
- So this figure corroborates a moneyline accuracy gap. It is **not** a beat-the-close verdict.
- Spread and total bets in the same script use an assumed −110 price, and the database has no spread or total prices at all.

## Database fingerprint

- File: `nbaodds/Data/OddsData.sqlite` (session scratchpad)
- Size: 4,632,576 bytes; modified Oct 18 14:44 (sandbox time)
- sha256: `4a803d41cd4597c1d898c0b131a58763dee8b64140be8f40c29b73c852e162d9`
- Tables: 36; total rows across all tables: 45,284 (duplicates included; 23,552 unique games used)
- Row counts by table:
  - odds_2007-08 1316, odds_2007-08_new 1316
  - odds_2008-09 1315, odds_2008-09_new 1315
  - odds_2009-10 1312, odds_2009-10_new 1312
  - odds_2010-11 1311, odds_2010-11_new 1311
  - odds_2011-12 1074, odds_2011-12_new 1074
  - odds_2012-13 1314, odds_2012-13_new 1314
  - odds_2013-14 1319, odds_2013-14_new 1319
  - odds_2014-15 1311, odds_2014-15_new 1311
  - odds_2015-16 1316, odds_2015-16_new 1316
  - odds_2016-17 1309, odds_2016-17_new 1309
  - odds_2017-18 1312, odds_2017-18_new 1312
  - odds_2018-19 1312, odds_2018-19_new 1312
  - odds_2019-20 1143, odds_2019-20_new 1143
  - odds_2020-21 1171, odds_2020-21_new 1171
  - odds_2021-22 1323, odds_2021-22_new 1323
  - odds_2022-23 1319, odds_2022-23_new 1319
  - odds_2023-24_new 1195; "2023-24" 1255
  - "2024-25" 1326; odds_2025-26 554
  - (The script reads `_new` tables where they exist; the 2023-24 plain and new counts differ, as the results file's `audit` block records.)

## Reproduction

1. Place `OddsData.sqlite` where the script's `DB` path points, and verify its sha256 above.
2. The script imports `sportsedge.sports.nba.ratings_model` from a repo checkout (`REPO` in the script). That module is **not** in this record and its version is not pinned here.
3. Paths in the script are session-local (under the Oct 18 scratchpad). Edit `DB`, `REPO` and the `sys.path` line before running elsewhere.
4. Expected output: `ML Brier diff (model - market): 0.01166` with the mean and CI above.

## Limits carried with the figure

- Untimestamped lines; no close-versus-open test is possible from this source.
- Single-line spreads and totals with no prices; the spread and total rows use an assumed −110.
- A ratings model that is results-only and online; the moneyline probability assumes a Normal margin with sd fitted on 2010-11..2021-22.
- The favorite-agreement subset is a data-quality filter (the spread column disagrees with the moneyline favorite 58-71% of the time before 2022-23), and it shapes what the 4,374 games mean.
