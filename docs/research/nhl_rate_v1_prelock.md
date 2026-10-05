# NHL rate model v1 — pre-lock

**Status:** windows and feature stand-ins locked before scoring 2025–26.
Research only. No phone-card pricing until a promotion PR freezes the artifact.

## Why this exists

`sportsedge/sports/nhl/rate_model.py` will not emit game rates without a versioned
`NHLRateParameters`. Official NHL boxscores do **not** include xG or GSAx.
Inventing those series would be a different model. v1 therefore maps official
counting stats onto the existing feature slots and writes that mapping down.

## Windows (one shot)

| Role | Games | Notes |
|---|---|---|
| Fit | 2024–25 NHL regular season | `gameType` REG only. Completed finals. |
| Validate once | 2025–26 NHL regular season | Most recent completed season as of 2026-09-30. |

If v1 fails 2025–26, v2 needs a new unused window. Do not retune on 2025–26.
2026–27 opening week is not a promotion window.

## Feature stand-ins (official `api-web.nhle.com` boxscore only)

All rates are **strictly prior** to puck drop (same-date games excluded).
Minimum 10 prior team-games or the game is skipped, not filled with a blend.

| Slot in `NHLRateParameters` | Official stand-in |
|---|---|
| `offense_xg` | Prior regulation GF / 60 |
| `opponent_xga` | Opponent prior regulation GA / 60 |
| `shot_share` | Prior SF / (SF + opponent SA) |
| `special_teams` | Prior PP goals/opportunity + opponent PP goals/opportunity, else 0 |
| `goalie_gsax` | 0.0 — no official GSAx. Starter save% is context until a later spec. |
| `rest` | Days since that team's previous completed game |
| `travel` | 0.0 — no official travel table in v1 |
| `lineup` | 0.0 — no official lineup strength in v1 |
| `home_ice` | 1 home / 0 away |

Ridge = 1.0 as already implemented in `training.fit_rate_parameters`.

## Gates on 2025–26 (must all hold)

Using the shared simulator in `sportsedge/sports/nhl/simulation.py` and the
fitted rates, on completed 2025–26 REG games:

1. Mean |predicted P(home regulation-or-OT win) − observed home win| excluding
   official ties/OT protocol mismatch ≤ 5 pp. Ties/OT/SO follow the existing
   sim (one deciding OT/SO goal).
2. Totals at 5.5 and 6.5: mean |gap| ≤ 6 pp.
3. Puck line ±1.5: mean |gap| ≤ 6 pp.
4. No market priced if either team has < 10 prior games.

Fail closed on goals/points/assists still. Those stay `NO_MODEL`.

## After a pass (separate promotion PR)

Freeze `NHLRateParameters` + dataset SHA. Phone card (#1246) may then price
ML / puck line / totals only. Dual clock if any later NHL evidence exists.
Parity test: research fit vs production copy within sim noise.

`NOT Model_P / NOT Truth Gate / NOT OFFICIAL`.
