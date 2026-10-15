# Result: NBA player layer v2 (minutes fix + player-level dispersion)

Pre-registration: `NBA_PLAYER_LAYER_V2_PREREG_20261013.md` (`ecc707e`, committed before v2 code was run on data). **Governance flag:** the prereg path needs ChatGPT registration. Same data, PIT rule, population and lines as v1. n = 23,499 player-games. Market baseline MISSING. Props WATCH/BLOCKED only.

| Stat | Line | v2 Brier | naive | v1 Brier |
|---|---|---|---|---|
| PTS | 9.5 | **0.1634** | 0.1805 | 0.1942 |
| PTS | 14.5 | **0.1295** | 0.1397 | 0.1534 |
| PTS | 19.5 | **0.0884** | 0.0953 | 0.1034 |
| PTS | 24.5 | **0.0548** | 0.0589 | 0.0638 |
| REB | 3.5 | **0.1807** | 0.1903 | 0.2018 |
| REB | 5.5 | **0.1403** | 0.1456 | 0.1557 |
| REB | 7.5 | **0.0893** | 0.0912 | 0.0985 |
| AST | 2.5 | **0.1504** | 0.1565 | 0.1616 |
| AST | 4.5 | **0.0976** | 0.0997 | 0.1042 |
| AST | 6.5 | **0.0541** | 0.0550 | 0.0579 |

Minutes MAE: v2 **4.85**, naive 5.05, v1 6.70.

## Decision (fixed rule): PTS / REB / AST / MINUTES **PASS_RESEARCH**

## Caveats: this does NOT show pregame skill
- **The comparison is unfair to naive, in v2's favor.** v2 uses the RETROSPECTIVE_AVAILABILITY_ORACLE: OUT teammates get 0 minutes and the remaining minutes are renormalized to 240. That redistributes absent players' minutes using knowledge of who actually played. The naive baseline does not use the oracle. Much of the gain may be that look-ahead.
- **Required follow-up:** a fair comparison needs either (a) the same oracle-renormalized minutes in the naive baseline, or (b) real timestamped pregame injury/availability evidence. That needs a new pre-registration.
- **Marginals only:** v2 marginals are not team-coherent per path. Joint use still relies on `allocate`.
- **Status:** no promotion and no eligibility change. Without verified availability evidence, production props are BLOCKED.
