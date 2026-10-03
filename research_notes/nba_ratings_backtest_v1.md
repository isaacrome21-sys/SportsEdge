# NBA ratings model v1 — out-of-sample backtest vs closing lines (2026-10-03)

Reproduce: `python scripts/backtest_nba_ratings_vs_lines.py` (clones the public sportsbookreview archive).

Verdict: **no NBA market is validated.** The scores-only rating model is less accurate than
the closing line (margin MAE 10.26 vs 9.86; total MAE 14.58 vs 14.16) and its disagreements
with the close lose (49% ATS / 49% O/U). Every NBA card output is a LEAN until a model
passes the pre-registered gate in the script.

Strongest non-validated signal: model total vs OPENING total, gap >= 6 → 389-297 (56.7%),
5/7 seasons above breakeven, p=0.013 — fails the Bonferroni bar (p<0.002). Bettors see DK
lines between open and close, so this is not directly actionable; treat as a research lead.

```
NBA_RATINGS_BACKTEST_SUMMARY
source https://github.com/flancast90/sportsbookreview-scraper.git data/nba_archive_10Y.json; games 13893
tuned on (2012, 2013, 2014) by score MSE: k=0.04 carry=0.5 k_league=0.005 (mse 458.0)
holdout 2015-2021: spread games 7696, total games 7696
margin MAE model 10.26 | close 9.86
total  MAE model 14.58 | close 14.16
ATS/OU rules (breakeven 52.38%; validation needs n>=200, p<0.0020, >=5/7 seasons above):
  spread_gap_close>=0.0      3703-3851 hit 49.0% p=1.000 seasons>0/7
  total_gap_close>=0.0       3713-3872 hit 49.0% p=1.000 seasons>0/7
  spread_gap_close>=2.0      1894-1947 hit 49.3% p=1.000 seasons>0/7
  total_gap_close>=2.0       2104-2233 hit 48.5% p=1.000 seasons>0/7
  spread_gap_close>=4.0      707-755 hit 48.4% p=0.999 seasons>1/7
  total_gap_close>=4.0       977-1082 hit 47.5% p=1.000 seasons>0/7
  spread_gap_close>=6.0      276-272 hit 50.4% p=0.838 seasons>2/7
  total_gap_close>=6.0       430-443 hit 49.3% p=0.970 seasons>2/7
  spread_gap_open>=0.0       4053-4109 hit 49.7% p=1.000 seasons>0/7
  total_gap_open>=0.0        4160-4050 hit 50.7% p=0.999 seasons>0/7
  spread_gap_open>=2.0       1824-1910 hit 48.8% p=1.000 seasons>0/7
  total_gap_open>=2.0        2190-2056 hit 51.6% p=0.856 seasons>2/7
  spread_gap_open>=4.0       645-654 hit 49.7% p=0.977 seasons>1/7
  total_gap_open>=4.0        910-838 hit 52.1% p=0.615 seasons>3/7
  spread_gap_open>=6.0       236-207 hit 53.3% p=0.371 seasons>4/7
  total_gap_open>=6.0        389-297 hit 56.7% p=0.013 seasons>5/7
  spread_anchored_adj>=0.5   331-376 hit 46.8% p=0.999 seasons>0/7
  total_anchored_adj>=0.5    2282-2187 hit 51.1% p=0.962 seasons>1/7
  spread_anchored_adj>=1.0   27-16 hit 62.8% p=0.112 seasons>3/7
  total_anchored_adj>=1.0    106-103 hit 50.7% p=0.709 seasons>1/7
  spread_anchored_adj>=1.5   2-3 hit 40.0% p=0.842 seasons>0/7
  total_anchored_adj>=1.5    4-1 hit 80.0% p=0.215 seasons>2/7
Moneyline (model N(margin,12) vs no-vig close), flat 1u:
  ml_edge>=0.02              n 6850 ROI -2.3% seasons+ 2/7
  ml_edge>=0.04              n 5413 ROI -2.0% seasons+ 3/7
  ml_edge>=0.06              n 4169 ROI -1.1% seasons+ 4/7
anchored coefs by held-out season: spread {2015: (-0.282, 0.1114), 2016: (-0.121, 0.1178), 2017: (-0.123, 0.0848), 2018: (-0.152, 0.0555), 2019: (-0.117, 0.0462), 2020: (-0.112, 0.0703), 2021: (-0.104, 0.0571)} | total {2015: (0.537, 0.0029), 2016: (0.515, -0.0191), 2017: (0.512, -0.033), 2018: (0.489, -0.0694), 2019: (0.445, -0.0784), 2020: (0.534, -0.0731), 2021: (0.508, -0.0855)}
VALIDATED MARKETS: NONE -> every NBA output is a LEAN, not a bet
```
