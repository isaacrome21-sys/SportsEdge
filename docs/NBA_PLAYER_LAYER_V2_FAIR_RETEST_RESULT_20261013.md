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

## Audit erratum — comparator cohort mismatch (2026-10-13; append-only)

The original numbers and decisions above are retained as the **as-run output**, not rewritten. The claim that the v2 candidate and `oracle-naive` shared an identical eligible-player cohort was incorrect. The v2 rotation normalizes over **played athletes in the prior-10-team-game rotation**, while the original oracle comparator normalized over **all actual target-game participants with history**, including athletes absent from the candidate rotation. These different denominators produced the reported minutes 4.85 versus 4.83; that difference is not interpretable as incremental minutes skill.

**Corrected disposition of this particular experiment:** `COMPARATOR_COHORT_MISMATCH`; the displayed PTS/REB/AST `PASS_RESEARCH` labels are the algorithm's historical as-run test labels, **not proof of a fair oracle-matched win**, verified pregame skill or betting eligibility. The separately preregistered V3 controlled retest (`docs/NBA_PLAYER_LAYER_V3_CONTROLLED_RETEST_PREREG_20261013.md` and `docs/NBA_PLAYER_LAYER_V3_CONTROLLED_RETEST_RESULT_20261013.md`) holds the candidate and comparator participant set and normalization identical. It reports minutes MAE 4.85 versus 4.85, an expected control tie, on the already-examined 2024–25 cohort. That later result is still **retrospective oracle-conditional research** without independently authenticated pre-tip availability or matched market prices. Props remain WATCH/BLOCKED; no activation, staking or validated betting edge.
