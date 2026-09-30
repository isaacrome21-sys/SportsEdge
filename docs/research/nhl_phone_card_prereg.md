# NHL phone card — fail closed until a frozen owner exists

There is no frozen NHL rate artifact on main. `sportsedge/sports/nhl/rate_model.py`
requires a versioned `NHLRateParameters` set learned from PIT-safe data. Inventing
weights to price opening-night games would be a new model, not a card wire.

This branch only adds the phone intake. Every market on the card is `NO_MODEL`
with an explicit reason from `market_capabilities.py` or
`NO_MODEL:FROZEN_OWNER_MISSING`.

## First scoring window (locked, not used yet)

Do not score a candidate on this branch.

When a frozen owner exists, the first held-out window is **2025–26 regular
season games with puck-drop on or after 2026-01-01 and before 2026-03-01**.
2024–25 and earlier may be used to fit. October–December 2025 is reserved as
a diagnostic slice only if the fit window is earlier. Opening week 2026–27 is
not a promotion window (too few prior same-season games; stand-in identity
must be written before any look).

## Markets

| Market | Card now | Why |
|---|---|---|
| ML / puck line / total / team totals | `NO_MODEL:FROZEN_OWNER_MISSING` | engine requires fitted rates |
| Regulation ML / periods | `NO_MODEL` | extra period state |
| Player shots / goalie saves | `NO_MODEL` | roles + starter required |
| Goals / points / assists | `NO_MODEL` | `player_props.py` unsupported |

`NOT Model_P / NOT Truth Gate / NOT OFFICIAL`.
