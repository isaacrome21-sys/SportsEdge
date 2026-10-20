# NBA spread and total — signed bias (Oct 19, 2026)

Script: `bias_nba.py` (blob c1663890) in this folder. It runs lines 1-165 of `bt_nba_lines.py` unchanged, so the games are the same 4,374 test games (2022-23..2025-26, favorite-agreement subset) as `nba_lines_results.json`. Output `nba_bias_results.json` sha256 `6c7ffe9558ce237985d5ea3f2f0f4bf183561f9ec816cef3f09a27b95770fadc` (12,521 bytes; not committed, reproducible by rerunning the script against the fingerprinted database and model). CIs: date-cluster bootstrap, seed 20261017, 2,000 resamples. Units: points.

Lines come from `OddsData.sqlite`, vintage unestablished. This is an accuracy diagnosis, not a market verdict.

## Spread, favorite-oriented (negative = less extreme than the favorite's line)

| Spread size band | n | model − line | model − actual | line − actual |
|---|---|---|---|---|
| all | 4,374 | −1.65 [−1.77, −1.54] | −1.15 [−1.56, −0.74] | +0.50 [+0.11, +0.88] |
| 0–3 | 856 | −1.09 [−1.29, −0.88] | −0.38 [−1.41, +0.66] | +0.71 [−0.30, +1.71] |
| 3–7 | 1,721 | −1.62 [−1.78, −1.46] | −0.66 [−1.35, −0.04] | +0.95 [+0.32, +1.55] |
| 7–11 | 1,116 | −1.80 [−2.01, −1.60] | −1.56 [−2.31, −0.80] | +0.24 [−0.47, +0.96] |
| 11+ | 681 | −2.20 [−2.58, −1.84] | −2.66 [−3.76, −1.46] | −0.46 [−1.45, +0.59] |

Reading: the model under-rates favorites, and the shortfall grows with the size of the spread. On big favorites (7+ points) it misses actual margins by 1.6 to 2.7 points. The line is close to unbiased on those games. Home-margin bias by season is near zero in every season (all CIs cross 0), so the error is compression, not a home/away tilt.

## Total, by line band (positive = prediction too high)

| Line band | n | model − line | model − actual | line − actual |
|---|---|---|---|---|
| <215 | 338 | +2.72 [+2.03, +3.37] | +4.15 [+1.54, +7.31] | +1.43 [−1.02, +4.48] |
| 215–225 | 1,242 | +1.18 [+0.79, +1.56] | +0.92 [−0.35, +2.26] | −0.26 [−1.42, +1.01] |
| 225–235 | 1,807 | −0.42 [−0.75, −0.09] | −0.87 [−1.86, +0.20] | −0.45 [−1.40, +0.55] |
| 235+ | 987 | −1.89 [−2.27, −1.52] | −1.66 [−2.95, −0.22] | +0.23 [−1.08, +1.67] |

By season, model − line: 2022-23 +0.34, 2023-24 +0.26, 2024-25 −0.40, 2025-26 −0.86 [−1.42, −0.32].

Reading: the model pulls totals toward the middle. It is too high on low-total games and too low on high-total games, and the line is not.

## One-line reason per market

- Spread: accuracy gap first. Cause on record: the ratings model compresses favorites toward even, worst on 7+ point spreads.
- Total: accuracy gap first. Cause on record: the model compresses totals toward the league middle, and in 2025-26 it runs low against the line.

Both are the same shape as the NFL #2384 underdog-compression signature. Nothing here is a play or a validated edge.
