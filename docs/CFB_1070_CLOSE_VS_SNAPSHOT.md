# #1070 sample check: CFBD historical lines are last-stored closes, not timed snapshots

Status: docs-only. CFB remains paused. Freeze unchanged. No pricing. Market data stays evaluation-only and out of `estimate_p`.

## Verdict

Free CFBD `GET /lines` (and the public sportsdataverse CFBD-derived mirror) is a **last-stored book line**, advertised historically as a **closing line**, **not** a timestamped snapshot series.

It is **not** certified kickoff-close for CLV / Truth Gate: there is **no line timestamp** on the row.

## Contract evidence

- Legacy swagger: `/lines` description = "Closing betting lines" (`CFBD/cfb-api` `swagger.yml`).
- Current v2 controller: "historical betting lines and results" (`CFBD/cfb-api-v2` `src/app/lines/controller.ts`).
- Schema splits `spread` / `overUnder` from `spreadOpen` / `overUnderOpen`; fields: `provider`, no capture time (`src/app/lines/types.ts`).
- Coverage: betting lines 2013–present (`docs-site/pages/data-availability.mdx`, verified 2026-09-03). Join key: CFBD `gameId`.
- Live cadence (about page): lines refresh every 15 minutes — that is the *ingest* interval. Historical `/lines` does **not** return that series.
- Free tier: 1,000 calls/month; betting lines included (`collegefootballdata.com/api-tiers`). JSON API; exporter also CSV.

## Sample checks (public CFBD-derived mirror, 2024)

Source: `sportsdataverse-data` release `cfb_matchup_line` / `cfb_matchup_line_2024.csv` (CFBD+ESPN derived; no API key). 764 games. `spread` vs `spread_open` differ on **729** rows, equal on 34, missing 1. That is incompatible with "one snapshot that is also the opener."

| game_id | week | start | home | away | spread (stored) | spread_open |
|---|---:|---|---|---|---:|---:|
| 401628319 | 1 | 2024-08-31 | Alabama | Western Kentucky | -34.17 | -31.25 |
| 401628335 | 2 | 2024-09-07 | Alabama | South Florida | -31.67 | -31.00 |
| 401628350 | 3 | 2024-09-14 | Wisconsin | Alabama | +15.17 | +9.33 |
| 401628363 | 4 | 2024-09-21 | Auburn | Arkansas | -2.50 | -3.50 |
| 401628373 | 5 | 2024-09-28 | Texas A&M | Arkansas | -6.83 | -6.33 |
| 401628379 | 6 | 2024-10-05 | Arkansas | Tennessee | +14.17 | +12.50 |

Fractional thirds are multi-provider averages in this mirror, not a single-book tick. Provider-level CFBD rows still use the same open-vs-stored split and still lack timestamps.

## What this does *not* prove

- Exact minute of last quote vs kickoff.
- Completeness by provider / season / ML.
- Agreement with an independently archived book close on these six games (no second free timestamped archive pulled here).

## Governance

Keep `close_time_certified=false`. Do not unpause CFB, unfreeze, or feed these numbers into `estimate_p` from this note.
