# Retrosheet gameinfo.csv archive — research only (2026-10-25)

This PR registers one narrow, public, historically useful Retrosheet input under tracker #2647. It does **not** replace MLB StatsAPI/Statcast, establish historical bookmaker odds, or feed Model_P.

## Official source, use rights and scope

- Catalog: https://www.retrosheet.org/downloads/csvdownloads.html
- Official direct game-information CSV ZIP: https://retrosheet.org/downloads/gameinfo.zip
- Retrosheet provides historical game-level information including teams, venue and umpire IDs. The catalog currently describes 1897–2025 coverage; **nothing here proves 2026 completeness**.
- Retrosheet allows commercial reuse but requires attribution. The receipt embeds the exact required attribution notice, and any downstream public SportsEdge output using the data must display that notice prominently.
- Statistics can be corrected in later releases; this download is an archival observation, **not** a point-in-time pregame lineup or price.

## Usage

Default invocation is offline and writes nothing:

```sh
python scripts/collect_retrosheet_gameinfo.py
```

For an explicit, bounded free capture:

```sh
python scripts/collect_retrosheet_gameinfo.py --live --output-dir captures/retrosheet_gameinfo
```

The collector permits only HTTPS Retrosheet-domain download URLs for the fixed official file; checks ZIP size and CRC; requires exactly one gameinfo.csv member, a nonempty unique CSV header and consistent nonempty row widths; **never extracts arbitrary ZIP member paths**; saves immutable raw ZIP bytes by SHA256; and appends a separate receipt for each observation time. It fails closed if the source is malformed, missing or changed unexpectedly.

Each receipt contains URL, actual UTC received-at time, archive SHA256/size, CSV member/header/row count, mandatory attribution, and explicit `event_identity_validated=false`, `pit_available=false`, `pricing_input=false`, `play_eligible=false`, `model_p=null`, and `research_only=true`.

## Work still required before analytical use

1. Inspect a real official 2026 capture and map Retrosheet's game and umpire identifiers to canonical MLB StatsAPI game IDs; verify collisions and doubleheaders.
2. Establish league/game-type/season inclusion, Retrosheet revision snapshots, and meaningful missing/unknown fields.
3. Isolate only historically prior observations for statistical modeling, with chronological train/test; never treat final outcomes as known at decision time.
4. Pair independent real sportsbook quote receipts and closes under existing OddsPapi/A–E governance before any betting evidence claim.
5. Independently review archive code, exact-head CI, and use rights before admitting records into any pricing/betting pipeline.

No new dependencies, workflow schedule, model math, promotion thresholds, or producer cards. Tests are synthetic/offline and do not assert a real-world source admission or an edge. Related owner audit: #2637.
