# Either-Pitcher ladder walk-forward: result

Spec: `MLB_EITHER_PITCHER_WALKFORWARD_SPEC_20261013.md`, committed at `4fc619e` before data fetch. Code: `sportsedge/mlb_either_pitcher_walkforward.py`, `scripts/run_mlb_either_pitcher_walkforward.py`. Cache (outside the repo): `/workspace/mlb_cache_pp`, holding 16 monthly schedules and 738 pitcher-season game logs. Research only. The market baseline is MISSING and settlement is UNVERIFIED_DK_RULES.

Scored events per season: 1,393 (2024) and 1,402 (2025). Both pitchers needed at least 5 usable starts *in that season*, so early-season games drop out. Events where a listed probable pitcher did not start: 3 (2024) and 4 (2025), excluded.

## Brier / log-loss: candidate vs naive (league-only)

| Market | Line | 2024 Brier c/n | 2025 Brier c/n | 2025 LL c/n |
|---|---|---|---|---|
| Hits allowed | 5.5 | 0.2279/0.2283 | **0.2322**/0.2340 | **0.6567**/0.6608 |
| Hits allowed | 6.5 | 0.2477/0.2492 | **0.2427**/0.2454 | **0.6786**/0.6839 |
| Hits allowed | 7.5 | 0.2008/0.2007 | **0.1829**/0.1851 | **0.5518**/0.5573 |
| BB | 2.5 | 0.2366/0.2418 | **0.2428**/0.2465 | **0.6787**/0.6862 |
| BB | 3.5 | 0.1288/0.1292 | **0.1416**/0.1429 | **0.4567**/0.4608 |
| ER | 2.5 | 0.2218/*0.2201* | **0.2176**/0.2196 | **0.6264**/0.6311 |
| ER | 3.5 | 0.2560/*0.2502* | **0.2489**/0.2499 | **0.6916**/0.6930 |

## Decision (fixed rule on 2025): HITS_ALLOWED **PASS_RESEARCH**, BB **PASS_RESEARCH**, ER **PASS_RESEARCH**

## Caveats (read before relying on this)
- **Small gains:** improvements are small (Brier −0.001 to −0.004). BB is the most consistent, passing both seasons at every line.
- **ER is unstable:** it **loses to naive in 2024** at both lines and only narrowly passes in 2025. Hits 7.5 is a tie in 2024.
- **Probable pitchers come from retrospective schedule data:** for past games the Stats API probable may reflect the actual starter, so pitcher identity could be slightly optimistic compared with a live pregame capture. Only 7 non-start exclusions suggests this.
- **Calibration:** mean p is under the hit rate for hits allowed and ER, and over it for BB.
- **Proposition is assumed:** the max-of-two contract is assumed. The DK proposition and void rules are unverified.
- **Next steps:** no promotion and no eligibility change. Next steps are forward pregame probable capture and live DK rules capture.
