# Result: NBA player layer v3 controlled re-test

Pre-registration: `NBA_PLAYER_LAYER_V3_CONTROLLED_RETEST_PREREG_20261013.md`, committed in aae18bf before the run. Both sides use the identical played-player set S and the same 240-minute normalization. Availability is a RETROSPECTIVE_AVAILABILITY_ORACLE for both. Props are WATCH ceiling; market baseline MISSING. n = 23,499 player-games (same scored population for both).

**Control check passes.** Minutes MAE is 4.85 vs 4.85, identical by construction, so the harness is consistent. Minutes = **FAIL** (a tie, as pre-stated).

| stat | line | cand Brier | naive Brier |
|---|---|---|---|
| PTS | 9.5 / 14.5 / 19.5 / 24.5 | 0.1634 / 0.1295 / 0.0884 / 0.0548 | 0.1744 / 0.1365 / 0.0936 / 0.0577 |
| REB | 3.5 / 5.5 / 7.5 | 0.1807 / 0.1403 / 0.0893 | 0.1858 / 0.1435 / 0.0906 |
| AST | 2.5 / 4.5 / 6.5 | 0.1504 / 0.0976 / 0.0541 | 0.1538 / 0.0988 / 0.0549 |

**Decision:** PTS, REB and AST are **PASS_RESEARCH**; MINUTES is **FAIL** (a tie).

## Reading
- **Where the edge comes from.** With minutes and player set held identical, the remaining edge comes only from the per-minute model: shrunk rates plus player-level NB dispersion, versus a scaled average with Poisson. Most of the stats edge is likely dispersion (Poisson is too narrow for points).
- **Gains are small for REB and AST.** The edge is about 1–6% relative.
- **No pregame validity.** Both sides know who played, so this says nothing about pregame minutes, and nothing about an edge against a market.
- **Reused cohort.** The cohort was already used, so this is a confirmatory control, not fresh validation.
