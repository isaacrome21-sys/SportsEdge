# NFL Participation Foundation — Reproduction Instructions

**Export date:** 2026-10-12 · **Branch:** `feat/nfl-participation-foundation-20261012`
**Commit:** `b4eaffc69` · **Patch base:** `34049bd8` (main at build time; NFL totals guard)
**Scope:** research-side infrastructure only (`sportsedge/participation/` + 4 test files).
Nothing in production imports this package. This export authorizes infrastructure
review only — not V2 locking, evaluation, or promotion.

## 1. Apply and test

```bash
git checkout 34049bd8            # or a main descendant; reconcile trivially if needed
git apply participation_foundation_20261012.patch
python3 -m pytest tests/test_participation_schema.py tests/test_participation_archive.py \
  tests/test_participation_reader.py tests/test_participation_collectors.py -q
# expected: 23 passed (verified at export time on the build worktree)
```

Dependencies: Python 3 + `pandas` (collectors/coverage) + `pytest`. Everything else is stdlib.

## 2. Reproduce the measurement

```bash
python3 -m sportsedge.participation.run_collection \
  --raw-dir data/participation_raw \
  --archive-dir data/participation_archive \
  --coverage-json sportsedge/participation/coverage_measured.json
```

This downloads the pinned sources below, stores raw payloads content-addressed
(`raw/<sha256>.csv`), appends collector receipts to `receipts.jsonl`, populates the
append-only archive (~1,004,996 records at build time), and recomputes the coverage
measurement. Compare against `coverage_measured_ORIGINAL.md` / `.json` in this export
(the builder's original measurements, preserved unchanged).

**Measured seasons default:** the fitting + extended corpora in
`sportsedge/participation/coverage.py` (`ALL_MEASURED_SEASONS`); the reported
headline population is regular-season team-games, 2019–2024 pooled (3,198).

## 3. Pinned sources

All data comes from nflverse public releases (CC-BY-4.0 data; code paths in
`sportsedge/participation/collectors.py`, `URL_TEMPLATES`):

| Signal | URL template |
|---|---|
| injuries | `https://github.com/nflverse/nflverse-data/releases/download/injuries/injuries_{season}.csv` |
| snap_counts | `https://github.com/nflverse/nflverse-data/releases/download/snap_counts/snap_counts_{season}.csv` |
| weekly_rosters | `https://github.com/nflverse/nflverse-data/releases/download/weekly_rosters/roster_weekly_{season}.csv` |
| depth_charts | `https://github.com/nflverse/nflverse-data/releases/download/depth_charts/depth_charts_{season}.csv` |
| schedule | `https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv` |

Upstream release files are mutable in principle; **the SHA-256 table in §4 is the
pin**. If a re-downloaded payload's hash differs from the table, the upstream bytes
changed and measurements may legitimately differ — treat any mismatch as a finding,
not a rounding difference. (Known instance: `snap_counts_2012.csv` is header-only
at the source; 2012 snap cells are UNAVAILABLE by measurement, not by assumption.)

## 4. Raw input SHA-256 (53 payloads, content-addressed)

Each payload's archive filename is its own SHA-256. Verify with
`sha256sum data/participation_archive/raw/*.csv` after a collection run.
The per-run receipts (`data/participation_archive/receipts.jsonl`) carry the same
hashes with fetch timestamps, row counts, and rejection tallies.

**depth_charts**

- `1a462b965a31f70a76568e0900485cec7f6ab202ade15df0a2d0d79f4ffc7537`
- `2c44efb1d96f8b8fef8a8ae42c44db340e97921745420d96b012778e184255bb`
- `328405d1feb09cc4b23922c26bf23adf7d6a6e894ba0e7305b88dda793710647`
- `37c5d02473ebec605aaf68747a50ec77f02347f68f16e69cb5d84862f75c6d3a`
- `45a315dd7f3e7837faf06a9c9cf995e1c131017a748482b2caaa111ffa0b9372`
- `4c64ee59666431c49cbc0a818cc3165886012cf72b545771a77c0805aa621b9c`
- `583f83842590e7e7d3417e0cd9c5c9e38f8696353bb754561d80e5583d2a98cf`
- `68a48cb5c3488aa505c2612c21797353c794c9ce5094e5071cc866373e71fd71`
- `7c8e3fc562a112faf76e093f36b2a81f6adc731a55d7d52e363f9d2d9b95b0d9`
- `91e3384ff13146c77f02fed2c3eca163d35868dd62da6b794c5b51df1d15b724`
- `cc8a9e6991236510ada3fd1a71ed0ebd3df91f2130c8abbf11e69150adc0eb7d`
- `e091a7fa0343fe3ae0bcee9202e1d8ca1ff859db398d20ab751017df29e85719`
- `f210a33774611f7f78a89af789b61c6289a2631a21227a1a3c63c973c23588b7`

**games_schedule**

- `8d0cacd8be859fe8b8d89ff80f54c40efc567e71bb486c83c6b83cc51e8881b4`

**injuries**

- `0d5139fbf41b0866517bd2bd5fd85bb20dbd4dd9bc36a706fed030a88731de6f`
- `1049fb9ff0fe7cfcf3ba8bfe1f5a35d3aba985c461c8fb7bf5201735b6d34254`
- `16b04e21da5aa3944cfa9c22cafcc84ed7e6d9866eaddf0344e9b8cbf2f63afe`
- `4724e1f37cc3076f564e997fbf269190e7dbe795a39315b903788e0a9c40065e`
- `498bce8e13cb64b2ab9bb0ad6cb81d0a63c2ddb24016c9fc90c2de2126fae449`
- `504e05968cb9c54ddc730fd9b6e7d1dd16a62db8029cc784d3d7bafcea7ff7cb`
- `5f0d60324e597edd1a2ced8540b04e40b51dd440591dd1df11b8d96343387c9e`
- `706cca82824214f6b73ba0c6e537d3ee39766a50c644b8974b9fc28d7518de90`
- `8b8ce2ed5bd45bbb709e5402efa4fe930d63fedfce111df9b1fea08ffa51f237`
- `b84c71cf23be81375bbca62f7d2c51d53fa75330fbcf9f598ec4ac17fea7d8be`
- `daddfe8e04ddc3a29bce14f362e774fbadfb274c807f1f0fde7b5bf32aaf6cdf`
- `e675fd5d86c3451d76e7c5d530095db1641347eb3f9796c9a30dd7a75e3ba634`
- `fbca54ef42594cc52facc0d8c8dd74802b812771b9e33032e44ae8c7e21b0360`

**snap_counts**

- `0018a4833fbf0f825286c1c27450c6254391b548d6c55bcde728e93e4816815a`
- `0cd52be8fa57f18503b670cb8263246c4f548375b768cbcad1c7a7462c98970d`
- `303b61aa5c33ffda863f93a750fc14483f397f9187ad502b1ce71e9b516a64c0`
- `512e35f17d076eb5d99b933c4a144eb95dcddf40c0320dbb397cae3c35683716`
- `802475aec59f0b125de85a6c35eb69e289a512bcf62d6be007d385ea8d613ebd`
- `841496252ada825c3c50d3ba9b4b26d3f4fabd0fedc5fb44f286ddaaa5bdb7e0`
- `84540709d9483552185c8ca3ef30b2f66fb94b30c3e6c21e7a27205f337f21d3`
- `8e4dae054a4749cf2d4919508d9161a6068fd67509979aefa385bfb3803d0ee5`
- `9a408b78a55f799110aed70de3564e157faf089ce9bed780d0368bf49ae13e0b`
- `9d1fdd557875b9a2c71d88e583da24a739dfca671edf8223d6171e39a421000e`
- `a2aa58efe093f8aa0ad5aadf09f81d8ec690a1183bd2dde68d20e7f109a9c335`
- `a778e24e9eb665ffe8f16093b03c5a263dca0250b3aa92bd6002f61f534bea59`
- `eab2fad2df99249d4061ed9c5c34d312cdba07cf3159d027d255bdc9b6526917`

**weekly_rosters**

- `074ecaeb9325de943c11f7bbc941425626985090ef8386f90cd837fa5cb5d4b3`
- `0b948cca8735a2417cbda14464f4532aeee58d871e2fcd8464a23e969e45789e`
- `1433f1f239784dde7fcb35349d211a9b83abfc0156337b72ec4f923abf715bd3`
- `198904f48eeebafc1f34028a00c1b8c0fc135aba04fc4b276e636ef87709751a`
- `262fd2f9a862c3b97275d91c60951f940a4e82989503b8359ac11b12a76c0e2f`
- `331022cd3b0c69d99c581f02b6fde6853e87ac431739c4b49841ee6e02893d6c`
- `76c47a629075ffd75f9c4ee49fadb6dad45396be486af897078fee5722969781`
- `88adfe0fba5cbedd260d7928ad373476d4fb168d0213cb52ef1163ed5d3056b7`
- `ab05dfeffe6f9a1d969133cd6740f1625d135bfad672aaa916adb609ab662883`
- `af6aa7b8aa7850c47fe307d548d66fa7c1cac88fe11e5951c781974cb6909e03`
- `bd6a50de334473c10f8058afa948fd0c6adc8a8b081da41c500cc0aa069c5312`
- `c3bca1ee53e63e21b964f1bb42c251e25b7b4b8c55210730dd4ded2f9d4a709a`
- `fd3fe005b676fe0ad8d88c50701d71adef4287501397c33f479c9765cd8c45d4`

## 5. Semantics under test (owner-specified distinctions)

- A prior-week roster record establishes **last-known membership** only; it cannot
  by itself establish **verified game-day reserve status** (reader lag rules +
  schema availability classes; see `reader.py`, `timing.py`, and the reader tests).
- Prior-game starts are legitimate historical inputs; the current game's **actual
  starter** (snap-derived) is a **retrospective label** — the reader refuses
  same-game snaps as features (`PIT_SAME_GAME_SNAPS_REFUSED_AS_FEATURE`).
- `CADENCE_INFERRED` availability is a distinct class from timestamp-verified
  availability end-to-end; it is never silently upgraded.

## 6. Known open items at export time (do not "fix" by editing this export)

- Questionable-designation gate: **99/100 — FAIL** under the strict identity bridge.
  A schedule-corroborated bridge sensitivity (105 cases) is under independent audit;
  it is NOT adopted.
- The original coverage report has three owner-verified defects (stale prior-season
  roster evidence in lag statistics; snap-derived starter identity presented beside
  pregame signals; absent-share reported as a proxy instead of the usable-feature
  intersection). A corrected, versioned sensitivity analysis
  (`coverage_sensitivity_v2.md/.json`) is being produced separately and will be added
  to this export on completion. The originals above remain unchanged for comparison.
- The populated archive's raw payloads are re-downloadable; their hashes (§4) and
  the receipts are the reproduction contract.
