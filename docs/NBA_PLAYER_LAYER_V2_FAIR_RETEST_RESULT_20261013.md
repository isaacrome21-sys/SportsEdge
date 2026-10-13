# Result: NBA player layer v2 fair re-test (oracle-matched naive)

Pre-registration: `NBA_PLAYER_LAYER_V2_FAIR_RETEST_PREREG_20261013.md` (`6dfe52a`, committed before code/run). **Governance flag:** that prereg path needs ChatGPT registration. Both candidate and baseline now use the same RETROSPECTIVE_AVAILABILITY_ORACLE (who played). Minutes are redistributed to 240 over players who played. n = 23,499. Market baseline MISSING; props WATCH/BLOCKED.

| Stat | Line | v2 | oracle-naive | (unmatched naive) |
|---|---|---|---|---|
| PTS | 9.5 | **0.1634** | 0.1743 | 0.1805 |
| PTS | 14.5 | **0.1295** | 0.1364 | 0.1397 |
| PTS | 19.5 | **0.0884** | 0.0935 | 0.0953 |
| PTS | 24.5 | **0.0548** | 0.0576 | 0.0589 |
| REB | 3.5 | **0.1807** | 0.1857 | 0.1903 |
| REB | 5.5 | **0.1403** | 0.1432 | 0.1456 |
| REB | 7.5 | **0.0893** | 0.0904 | 0.0912 |
| AST | 2.5 | **0.1504** | 0.1537 | 0.1565 |
| AST | 4.5 | **0.0976** | 0.0987 | 0.0997 |
| AST | 6.5 | **0.0541** | 0.0549 | 0.0550 |

Minutes MAE: v2 4.85 vs oracle-naive **4.83**.

## Decision (fixed rule): PTS PASS_RESEARCH, REB PASS_RESEARCH, AST PASS_RESEARCH, **MINUTES FAIL**

## Interpretation
- **About a third (≈31%) of v2's PTS edge was the oracle**, e.g. PTS 14.5: gap 0.0102 → 0.0070. The rest survives matching.
- **v2 minutes add nothing** over oracle-redistributed last-10 minutes (4.85 vs 4.83). The remaining stat gain likely comes from shrunk per-minute rates and the player-level NB dispersion, not from minutes.
- **Both arms still know who played.** This is not pregame skill. Real timestamped availability evidence is required before any claim. No promotion.
