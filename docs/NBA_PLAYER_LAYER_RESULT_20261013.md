# Result: NBA player layer evaluation (2024-25)

Pre-registration: `NBA_PLAYER_LAYER_PREREG_20261013.md` (`09a3f1b`, committed before data fetch). **Governance flag:** that prereg path needs a ChatGPT freeze-inventory mapping. Code: `sportsedge/sports/nba/player_harness.py`, `scripts/run_nba_player_harness.py`. Cache: `/workspace/nba_cache_players` (outside the repo), 1,234 ESPN box scores and 26,275 player-game logs. The market baseline is MISSING. The prop status ceiling is WATCH (asserted on every row; none PLAY).

**Availability caveat: RETROSPECTIVE_AVAILABILITY_ORACLE.** Who played in the target game is known (look-ahead). This favors the candidate, which still loses.

n = 23,499 player-games.

| Stat | Line | Brier candidate | Brier naive (last-10 Poisson) |
|---|---|---|---|
| PTS | 9.5 | 0.1942 | **0.1805** |
| PTS | 14.5 | 0.1534 | **0.1397** |
| PTS | 19.5 | 0.1034 | **0.0953** |
| PTS | 24.5 | 0.0638 | **0.0589** |
| REB | 3.5 | 0.2018 | **0.1903** |
| REB | 5.5 | 0.1557 | **0.1456** |
| REB | 7.5 | 0.0985 | **0.0912** |
| AST | 2.5 | 0.1616 | **0.1565** |
| AST | 4.5 | 0.1042 | **0.0997** |
| AST | 6.5 | 0.0579 | **0.0550** |

Minutes MAE: candidate **6.70** vs naive **5.05**.

## Decision (fixed rule): PTS FAIL, REB FAIL, AST FAIL, MINUTES FAIL

## Likely causes (diagnosis only; any fix needs a new pre-registration)
- `build_rotation` counts recent games a player missed as 0 minutes. With oracle OUT players zeroed and the rest renormalized to 240, returning or newly promoted players are badly under-projected. The naive averages only games played.
- Allocation adds team-total and multinomial variance on top of player variance, so the distributions are too wide relative to a per-player Poisson.

No promotion. Props remain WATCH/BLOCKED.
