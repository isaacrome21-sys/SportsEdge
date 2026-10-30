# CBB data layer — registered research sources

`sportsedge/cbb_data_sources.py` + `scripts/collect_cbb_data.py` register
the free CBB (men's college basketball) data layer as **research-only**
sources: every manifest they emit is labeled `research_only`,
`validation_status: NOT_VALIDATED`, `pricing_impact: NONE`,
`staking_allowed: false`. **No CBB engine exists in this program yet**
and nothing in any pricing path imports the collectors. This
registration is the data layer only.

**Scope note (recorded, not a filter):** Illinois college teams are out
of scope for CBB pricing in this program. The archives intentionally
retain all teams (Illinois appears in them); the exclusion binds any
future pricing use, never the archive. The note is stamped into every
manifest as `scope_note`.

## Sources (live-probed 2026-10-24)

### 1. ESPN MBB play-by-play — SportsDataverse release

The files behind hoopR's `load_mbb_pbp()` (hoopR's own loader reads the
`.rds` form; this stdlib collector archives the published plain-CSV form
of the same release).

- Release: `sportsdataverse/sportsdataverse-data`, tag
  `espn_mens_college_basketball_pbp`, asset `play_by_play_{season}.csv`
  (also `.parquet` / `.rds`). Seasons **2006–2026** (plus a small 2003
  stub file), one file per season. Season = ending year: 2026 is the
  completed 2025-26 season.
- The whole release was refreshed **2026-10-18**. Sizes per season:
  CSV 123 MB (2006) growing to 1.35 GB (2026); parquet 7–90 MB;
  rds 8–82 MB. The collector streams and stores gzip-compressed.
- Schema (63 columns, verified from the 2026 file): play text/type,
  period/clock, running `away_score`/`home_score`, team ids/names,
  athlete ids, `game_date`, and ESPN's published `game_spread` fields.
- Currency limit: **no 2027 file exists yet** — the 2026-27 in-season
  play-by-play is not yet published in this release (the completed
  2025-26 season is fully present). The probed range is therefore
  capped at 2026 and the collector refuses 2027 for this source.
- The older `saiemgilani/hoopR-data` git tree is frozen at the 2023
  season (last push 2023-04-05); the SportsDataverse releases above are
  the living distribution and the one registered here.

### 2. NCAA MBB play-by-play — SportsDataverse release

The files behind hoopR's `load_ncaa_mbb_pbp()` (stats.ncaa.org-derived,
produced by the `ncaa-mbb-hoops-data` pipeline).

- Release: tag `ncaa_mbb_pbp`, asset `ncaa_mbb_pbp_{season}.csv.gz`
  (also `.parquet` / `.rds`). Seasons **2010–2026** (hoopR's loader
  documents 2011–2026; the release carries a 2010 file, which the
  collector's probed range includes). Published 2026-08-12, updated
  2026-10-01. CSV.GZ 46–100 MB per season.
- Schema (87 columns, verified from the 2026 file): event stream with
  running scores, **reconstructed possessions** (`poss_num`,
  `poss_team`, `poss_length`, `is_transition`), **full 5-man lineups**
  for both teams (`home_1`–`home_5`, `away_1`–`away_5`, with player ids
  and clean names), `is_garbage_time`, and a built-in crosswalk
  (`home_espn_team_id`, `espn_game_id`, …).
- Shot coordinates are **not** in this file: they live in the sibling
  `ncaa_mbb_shots` release (coordinates only from 2019, per hoopR docs)
  and are not collected here.

### 3. BartTorvik T-Rank team ratings — direct season CSV

- `GET https://barttorvik.com/{season}_team_results.csv` — free, no
  key, no account. Columns: rank, team, conf, record, AdjOE (+rank),
  AdjDE (+rank), Barthag, projected W/L, and more.
- **Currency question — settled with evidence.** The toRvik/hoopR
  wrapper documentation dates to 2022, which made the underlying feed's
  currency doubtful. It is not: on **2026-10-24** the **2027** file
  (the 2026-27 season, all 365 teams at 0-0) was already live — Duke #1
  (AdjOE 120.4, AdjDE 91.0, Barthag 0.9616) — and the **2026** file
  holds the completed 2025-26 final ratings (Michigan #1, 37-3,
  Barthag 0.9819). Depth verified in this same pattern back to 2010
  (347–365 team rows per season; e.g. 2015 Kentucky 38-1 at #1).
- Caveat: the human-facing `trank.php` page answers plain HTTP clients
  with a "Verifying Browser..." interstitial; the season CSV path is
  served directly. The collector uses only the CSV path and fails
  closed if a non-CSV body ever comes back.

## Cross-checks (2026-10-24)

- **ESPN PBP final score vs ESPN's own game record:** the 2026 file's
  New Mexico State vs Sam Houston game (2025-12-21, `game_id`
  401804830) derives **New Mexico State 87, Sam Houston 78** from its
  running-score columns; ESPN's summary record for that event says
  Final, 87–78. **Match.**
- **NCAA PBP final score vs ESPN:** the 2026 NCAA file's Buffalo vs
  Southern Miss. game (2025-11-03) derives **Buffalo 85,
  Southern Miss. 79**; ESPN's summary for its `espn_game_id`
  (401823425) says Final, 85–79. **Match** — and the file's built-in
  ESPN crosswalk is what made the join exact.
- **Torvik known-team row:** 2027 preseason #1 Duke, present with
  plausible adjusted efficiencies and a 0-0 record, fetched live on
  2026-10-24 (before the season tips). **Present, plausible, dated.**

## Command

```bash
python3 scripts/collect_cbb_data.py --source torvik_team_ratings --season 2027
python3 scripts/collect_cbb_data.py --source ncaa_mbb_pbp --season 2026
python3 scripts/collect_cbb_data.py --source espn_mbb_pbp --season 2026
```

Each run writes `{archive_dir}/{source}/{season}.{ext}` plus a
`{season}.manifest.json` (source URL, `retrieved_at`, row count, schema
header, downloaded and stored sha256). Exit 0 with the manifest on
stdout; exit 2 on any source/contract failure, with no partial file or
manifest left behind. `verify_manifest()` re-hashes a stored file
against its manifest offline.

## Limits

- ESPN PBP lags the live season: the in-season (2026-27) file does not
  exist yet in the release; plan on completed-season granularity until
  SportsDataverse publishes it.
- Full-season ESPN CSVs are up to ~1.35 GB raw; collection is a
  deliberate, per-season operation, not a casual refresh.
- Torvik ratings are a model output (Barthag/AdjOE/AdjDE), not raw
  statistics; they are registered as a research reference, and any
  future engine use still needs the program's validation gates.
- KenPom is paid and is deliberately not a source here.
