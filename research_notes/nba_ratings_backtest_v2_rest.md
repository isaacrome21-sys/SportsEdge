# NBA ratings model v2 (rest / back-to-back) — out-of-sample backtest (2026-10-04)

Reproduce: `python scripts/backtest_nba_ratings_v2_rest.py` (clones the same public sportsbookreview archive as v1).

Pre-registered in the script docstring before the holdout was run: v1 model + rest adjustment
(b2b flags, capped rest-day difference) fit by OLS on 2012-14 only, frozen, scored on 2015-21.
Because v1 already looked at that holdout, the Bonferroni denominator counts v1's 25 tests plus v2's 13 (alpha 0.0013).

Verdict: **still no NBA market validated.** Rest helps the raw model a little (margin MAE
10.26 → 10.24) but the closing line already prices it: fading a back-to-back team vs a rested
opponent at the close went 953-962 (49.8%). The v1 lead (model total vs OPENING total, gap ≥ 6)
reproduces with v2 (389-305, 56.1%, above breakeven in all 7 seasons) but p=0.029 is far from 0.0013,
and DK lines seen at bet time are not the opener. It stays a research lead, not a bet.

No change to the card: every NBA output remains a LEAN/PASS.

```
NBA_RATINGS_V2_REST_BACKTEST_SUMMARY
base v1 params k=0.04 carry=0.5 k_league=0.005
rest coefs (fit on (2012, 2013, 2014) only): margin c0,c_b2b,c_rest=[-0.34, 1.026, 0.399] | total d0,d_b2b=[0.261, -0.026]
b2b share of holdout team-games: 17.1%
margin MAE v1 10.26 | v2 10.24 | close 9.86
total  MAE v1 14.58 | v2 14.59 | close 14.16
rules (breakeven 52.38%; tests v1 25 + v2 13; gate n>=200, p<0.0013, >=5/7 seasons):
  v2_spread_gap_close>=2.0     1823-1867 hit 49.4% p=1.000 seasons>0/7
  v2_total_gap_close>=2.0      2115-2240 hit 48.6% p=1.000 seasons>0/7
  v2_spread_gap_close>=4.0     683-720 hit 48.7% p=0.997 seasons>0/7
  v2_total_gap_close>=4.0      982-1087 hit 47.5% p=1.000 seasons>0/7
  v2_spread_gap_close>=6.0     239-238 hit 50.1% p=0.851 seasons>2/7
  v2_total_gap_close>=6.0      426-452 hit 48.5% p=0.990 seasons>1/7
  v2_spread_gap_open>=4.0      627-602 hit 51.0% p=0.838 seasons>3/7
  v2_total_gap_open>=4.0       925-843 hit 52.3% p=0.530 seasons>4/7
  v2_spread_gap_open>=6.0      208-192 hit 52.0% p=0.580 seasons>4/7
  v2_total_gap_open>=6.0       389-305 hit 56.1% p=0.029 seasons>7/7
  fade_b2b_vs_rested_close     953-962 hit 49.8% p=0.990 seasons>1/7
  under_both_b2b_close         148-170 hit 46.5% p=0.984 seasons>2/7
  v2_ml_edge>=0.04             n 5296 ROI -1.8% seasons+ 3/7 (needs ROI>0 in >=5/7 and is not validated by ROI alone)
VALIDATED MARKETS: NONE -> every NBA output stays a LEAN, not a bet
```
