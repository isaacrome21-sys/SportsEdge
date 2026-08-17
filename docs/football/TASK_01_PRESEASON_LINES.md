# Football Roadmap Task 1 — nflreadpy Preseason Line Availability

**Status:** COMPLETE

**Result:** NO — the nflverse schedules dataset consumed by `nflreadpy.load_schedules()` does not currently contain preseason (`game_type == "PRE"`) rows, so it cannot supply historical preseason `spread_line` / `total_line` targets for model calibration.

## Verification performed

Checked on 2026-08-16/17 against the current upstream nflverse schedule source used by nflreadpy.

1. `nflreadpy` documents `load_schedules()` as the schedule/results loader.
2. The current `nflverse-data` `schedules` release states that its schedule data is maintained from `nflverse/nfldata` and exposes `games.csv` / `games.parquet` for `nflreadpy.load_schedules()`.
3. The current upstream `nflverse/nfldata/data/games.csv` schema includes `game_type`, `spread_line`, and `total_line`.
4. Searching the complete current upstream `games.csv` for `,PRE,` returns no matches.
5. The upstream nfldata dataset documentation also states that the games dataset does not include preseason.

## Consequence

The roadmap's preseason decision is confirmed: do **not** fit or promote a preseason-specific predictive feature layer from nflreadpy schedule lines. Keep the 2026 preseason lane in **SHADOW** and use it only for live-fire rehearsal of event binding, market discovery, no-vig, gate evaluation, and logging.

This does **not** mean preseason odds can never be modeled. It means a separate, point-in-time historical preseason line source would be required before preseason calibration or promotion is scientifically defensible. That source is outside Football v1 scope.

## Acceptance

- [x] Documented yes/no in repo.
- [x] Answer is explicit: **NO**.
- [x] Preseason predictive layer remains frozen per §1.1 / §1.3 of `docs/FOOTBALL_ROADMAP.md`.

## Upstream references

- https://github.com/nflverse/nflreadpy
- https://github.com/nflverse/nflverse-data/releases/tag/schedules
- https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv
- https://github.com/nflverse/nfldata/blob/master/DATASETS.md
