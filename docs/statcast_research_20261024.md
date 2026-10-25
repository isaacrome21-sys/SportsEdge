# Statcast (Baseball Savant) research archive intake

`scripts/collect_statcast_research.py` registers Baseball Savant's Statcast
CSV export as a governed research source: the pitch-level quality layer
(exit velocity, release spin, whiffs, xwOBA) under the MLB pitcher-K family.

It is the scoped, stdlib-only sibling of `scripts/refresh_statcast_daily.py`
(which aggregates via pybaseball into daily snapshots for the pitcher-K
skill lane, see `docs/MLB_PITCHER_K_STATCAST_SKILL_SOURCE_V1.md`). This
collector archives **raw per-pitch rows with provenance** for small,
deliberate windows. It changes nothing about the existing daily lane and
imports nothing from the pricing path.

## Defaults and examples

No flag means **zero network requests** — the command only prints the URL:

```bash
python3 scripts/collect_statcast_research.py --date 2026-10-23
```

A live research pull is explicit and scoped (one day default, hard cap
3 days per pull):

```bash
python3 scripts/collect_statcast_research.py --date 2026-10-23 --live \
  --out-dir research/statcast_archive
python3 scripts/collect_statcast_research.py --date 2026-10-23 --live \
  --pitcher-id 694819
```

Filters (`--pitcher-id`, `--batter-id`, `--game-pk`) are applied
**client-side**: the provider's own `player_id` parameter is unreliable
(verified 2026-10-24 — a pull scoped to one pitcher returned every pitch
of the game), so the collector never trusts it.

## Scoping discipline

- Window cap: 3 days. A regular-season day is ~3,900 rows / ~2.7 MB; a
  postseason day is far smaller. Larger history is built from many small
  pulls, never one wide one.
- The provider caps responses at **25,000 rows** (verified 2026-10-24:
  malformed/unscoped queries returned exactly 25,000 rows, 12–17 MB,
  35–47 s, silently truncated). A pull that hits the cap is **refused**
  (`PAYLOAD_ROW_CAP_SUSPECT`) rather than archived as if complete.
- Missing required columns, empty payloads, and filters that remove every
  row all fail closed.

## Probe evidence (2026-10-24, live from the research sandbox)

| Pull | Rows | Bytes | Time |
|---|---|---|---|
| WS G1 2026, 2026-10-23 (1 game) | 264 | 181,952 | ~2 s |
| Regular season, 2026-09-27 (14 games) | 3,928 | 2,700,304 | 7.8 s |
| Statcast era start, 2015-04-06 (14 games) | 3,727 | 2,166,751 | 9.0 s |

No HTTP throttling (403/429) was observed on scoped pulls spaced seconds
apart. Oversized responses are slow (~0.4 MB/s), which is the practical
reason for the window cap.

## Cross-check vs MLB StatsAPI (admission evidence)

2026 World Series Game 1, game_pk 849805 (Tampa Bay 2 @ Milwaukee 3,
2026-10-23). Statcast-derived aggregates from this collector's own
manifest vs the StatsAPI box score — **all nine pitchers reconcile
exactly** on thrown pitches and strikeouts:

| Pitcher | Thrown (Savant) | Thrown (StatsAPI) | K (Savant) | K (StatsAPI) |
|---|---|---|---|---|
| Nick Martinez | 73 | 73 | 5 | 5 |
| Steven Matz | 31 | 31 | 0 | 0 |
| Kevin Kelly | 12 | 12 | 0 | 0 |
| Garrett Cleavinger | 10 | 10 | 0 | 0 |
| Cole Sulser | 4 | 4 | 0 | 0 |
| Jacob Misiorowski | 78 | 78 | 3 | 3 |
| Abner Uribe | 15 | 15 | 2 | 2 |
| Aaron Ashby | 20 | 20 | 3 | 3 |
| Trevor Megill | 20 | 20 | 1 | 1 |

Two source semantics explain the only raw-count differences, and both
are encoded in the collector:

- **Strikeout events** are `{"strikeout", "strikeout_double_play"}`.
  Uribe's second strikeout is the double-play form (strikeout + caught
  stealing); counting only `"strikeout"` undercounts him 1 vs 2.
- **Pitch-clock violation rows** (`description` = `automatic_ball` /
  `automatic_strike`) are recorded by Savant but are not thrown pitches;
  StatsAPI excludes them from `numberOfPitches`. Misiorowski has 79
  Savant rows, 78 thrown. The normalized output flags these rows
  `is_thrown_pitch = false` so counts reconcile exactly.

## What is saved

Per pull, under the out-dir (default `research/statcast_archive/`):

- `statcast_raw_<window>.csv` — the provider response, byte-unchanged.
- `statcast_pitches_<window>.csv` — per-pitch rows (all provider fields)
  plus provenance (`source`, `source_url`, `fetched_at_utc`) and the
  flags `is_thrown_pitch`, `is_strikeout_event`.
- `statcast_manifest_<window>.json` — window, filters, fetch time, raw
  byte count / row count / **sha256**, normalized row count, per-pitcher
  game summary, and the labels below.

## Workflow boundaries

- **Research/archive only.** Not a pricing input, not a model
  probability, no `PLAY` authorization, no staking or forward-clock
  authority. The manifest carries these labels on every pull.
- Registration is not admission to any pricing or validation path; any
  future use in a model must clear the program's chronological
  out-of-sample bar against the existing model and a market baseline.
- The pybaseball daily lane (`refresh_statcast_daily.py`) is unchanged.
- No account, key, or login is required or used; the endpoint is public.

## Honest limits

- History depth: pitch-level Statcast exists from 2015 (verified by the
  2015-04-06 pull above); earlier seasons are not available from this
  source, and some tracking fields are thinner in early years.
- The endpoint is a public web export with no SLA; it can be slow on
  oversized responses and caps at 25,000 rows. Realistic volume is one
  scoped pull (≤3 days, typically ≤ ~12k rows) at a time.
- Batted-ball fields (`launch_speed`, `estimated_woba_using_speedangle`)
  are populated only on balls in play, by the source's design.

Provider endpoint:
- https://baseballsavant.mlb.com/statcast_search/csv (type=details)
