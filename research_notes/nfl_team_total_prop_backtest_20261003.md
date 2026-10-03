# NFL team totals and player props: backtest (Oct 3, 2026)

Script: `scripts/research_nfl_team_total_backtest.py --games nfldata/data/games.csv`
(nflverse/nfldata `games.csv`, 2006–2026 wk 4).

## Team totals: no edge, so track only

There are no free historical DK team-total closes. The proxy is the closing implied team total, `total/2 ± spread/2`, posted at the nearest half point. Breakeven is 52.4% at -110. Pushes are excluded.

| Test (walk-forward, strictly prior data) | 2012–17 | 2018–26 OOS |
|---|---|---|
| A: EWMA off/def residual, α=0.05, \|adj\|≥0.25 | 50.0% (1241) | 50.5% (1092) |
| A: α=0.10, \|adj\|≥0.25 | 49.0% (839) | 51.7% (849) |
| A: α=0.10, \|adj\|≥0.5 | 51.3% (156) | 52.0% (50) |
| A: α=0.20, \|adj\|≥0.25 | 51.8% (197) | 53.1% (360) |
| B: bet toward unrounded implied (0.25 rounding) | 52.2% (1564) | 51.5% (1951) |
| Always over / always under | 49.9% / 50.1% | 49.8% / 50.2% |

Only one cell clears 52.4%: α=0.20 at 53.1% on n=360. That is 1 of 11 configurations, the SE is about 2.6 pp, and the same config was below breakeven in 2012–17. This is noise, not an edge. The closing implied team total is efficient against recency signals. **Verdict: team totals are TRACK ONLY.**

An earlier draft scored 56.9% OOS, but only because model gap and rounding gap were mixed together. With the rounding effect isolated (test B), the result is about 51.5%.

## Player props: can't validate, so track only

nflverse has player box scores but no historical prop lines or prop closes. That makes an out-of-sample test against closing prices impossible on free data. The #898 role-based challenger stays research only. **Verdict: props are TRACK ONLY.** A prop could be revisited if a source of historical prop closes becomes available.

## NFL card status after this

- Spreads: held (#1248). Spread-gap test inconsistent.
- Totals: lean only (49.7% OOS).
- Team totals: track only (above).
- Props: track only (no closing-line history).
- `BET_PROVEN_MARKETS` stays empty. The card never labels an NFL market a bet.

NOT Model_P / NOT Truth Gate / NOT OFFICIAL
