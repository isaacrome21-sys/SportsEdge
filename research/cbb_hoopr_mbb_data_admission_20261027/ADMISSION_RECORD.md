# Admission record — hoopR men's basketball substrate (schedules + player box scores)

**Status: SAMPLE-VERIFIED / ADMISSION PROPOSED — DESIGN ONLY — NOT VALIDATION —
NO FORWARD-CLOCK CREDIT — NO PLAY ELIGIBILITY.**
Prepared 2026-10-27 (retrieval 2026-10-28T03:56:18Z) for independent review.
Admission takes effect only if this PR is merged after independent (Rocky)
review, and even then the substrate is a **design / baseline input only**.

Every factual claim carries an evidence state: **verified-by-pull** (checked
against bytes or API responses fetched from the SportsEdge runtime) or
**documented-only** (provider documentation; not reproduced here).

## 1. Source and provenance

- **What the substrate is:** ESPN-derived NCAA Division I men's basketball
  schedules and player box scores, assembled by the **sportsdataverse**
  project and consumed by the R package **hoopR** (`load_mbb_schedule`,
  `load_mbb_player_box`, …). The underlying game data originates with ESPN;
  sportsdataverse is the packager, not the originator (documented-only as
  to ESPN origination; the ESPN-shaped schema below is verified-by-pull).
- **Canonical download route (verified-by-pull):** GitHub **release assets**
  of `sportsdataverse/sportsdataverse-data`, under rolling tags including
  `espn_mens_college_basketball_schedules` and
  `espn_mens_college_basketball_player_boxscores`. The
  `sportsdataverse/hoopR-mbb-data` repository itself carries **no GitHub
  releases** (verified-by-pull: releases list is empty); it is the
  pipeline/docs repo (in-tree `mbb/` parquet directories) and points
  consumers at the sportsdataverse-data releases.
- **Licenses (verified-by-pull):** `sportsdataverse-data` — MIT;
  `hoopR-mbb-data` repo contents — CC BY 4.0 (its `LICENSE.md`). ESPN's own
  terms govern the underlying data. This repo commits **hashes, manifests
  and retrieval code only — no sample data files**.

## 2. The pin rule — release tags are rolling, so a tag pins nothing

**Verified-by-pull mutability finding:** the schedules release was
*published* 2023-03-29, yet its assets were still being **replaced in
place** on 2026-10-18; the 2027 parquet asset was updated 2026-10-18 while
its CSV twin in the same release was updated 2026-09-15. A release tag is a
label on a moving target.

Therefore the pin for every asset in this admission is the full tuple:

> **release tag + release ID + asset ID + asset size + asset `updated_at`
> + SHA-256 of the downloaded bytes**, all recorded in
> `sample_manifest.json` at pull time.

The committed script `pull_hoopr_mbb_samples.py` re-downloads every pinned
asset and compares size + SHA-256. Any drift is
`SOURCE_CHANGED_AFTER_SNAPSHOT` — a **refusal**, never silent acceptance —
and a drifted asset may only re-enter through a successor manifest with its
own review. Formats (parquet / CSV / RDS) are pinned independently; one
format's pin never vouches for another.

## 3. Hash-verified samples (2026-10-28)

| Asset | Tag | Asset ID | Bytes | SHA-256 | Evidence |
|---|---|---|---|---|---|
| `mbb_schedule_2027.parquet` | espn_mens_college_basketball_schedules | 653456795 | 133,319 | `a3f51c1a83ec9ad4d037baa53bbdd79d25b78ef3882f465e779320b314b0ae21` | verified-by-pull (bytes/hash) |
| `mbb_schedule_2027.csv` | espn_mens_college_basketball_schedules | 565252739 | 2,247,130 | `63a6ec8f565a11dfbaab54ea656cc6fc47e19e3d1b29eb40f0824649f56eb9fa` | verified-by-pull (bytes/hash/content) |
| `player_box_2026.parquet` | espn_mens_college_basketball_player_boxscores | 540047372 | 3,397,951 | `62505219f40b4a83d9a89883620b927a336e6c78c4cea1d711db086641e2b810` | verified-by-pull (bytes/hash); schema documented-only |
| `mbb_schedule_crosswalk_2026.csv` | mbb_crosswalk | 678171335 | 694,527 | `9e4424750c7bd5b250ab61e09a85db877a25b95cad8e2409600c69cbdb68551f` | verified-by-pull (columns/rows) |
| `mbb_team_crosswalk_2026.csv` | mbb_crosswalk | 592679588 | 65,478 | `f492b4e2cbed5da6faaf48c087638a32213334a934938c57f5e7498accfde0d7` | verified-by-pull (columns/rows) |

**Content check on the 2027 schedule CSV (verified-by-pull):** 1,629 rows,
`game_date` range 2026-11-02 → 2027-03-06; **0 games on 2026-11-01 and
exactly 50 on 2026-11-02** — independently corroborating the checked 2027
schedule evidence already on file. ESPN identifiers are present
(game `id`, `home_id`, `away_id`, venue and status fields). At 1,629 rows
against roughly 5,800 games in a full Division I season this file is a
**preliminary, partial schedule — NOT an admitted slate**. No slate is
admitted by this record; slates enter only through the CBB capture /
readiness process (see `research/cbb_season_prep_20261020/`).

**Player box caveat:** the runtime had no working parquet reader at
admission time (broken wheel), so `player_box_2026.parquet` is admitted on
bytes + hash, with row counts/schema **documented-only** from hoopR's
documentation. A schema-verified successor manifest is required before any
player-box-dependent design consumes it.

## 4. Identity crosswalk — OPEN ITEM, not admitted, no mappings invented

Joining this substrate to Torvik ratings and to NCAA/official records
requires an identity crosswalk across **ESPN game/team IDs ↔ Torvik
(team names / `bart_muid`) ↔ NCAA IDs**. State of that item:

- A provider crosswalk **exists**: the `mbb_crosswalk` release (samples 4–5
  above). Verified-by-pull column sets — schedule crosswalk: `espn_game_id`,
  `bart_muid`, `bart_team1`, `bart_team2`, `kp_game_id`, `fox_game_id`,
  `yahoo_game_id`, `match_method`, `match_confidence` (6,319 rows for
  2026); team crosswalk: `espn_team_id` ↔ `bart_team` ↔ `kp_team` ↔
  fox/yahoo IDs with per-source `match_confidence` (362 rows).
- It is **NOT admitted as an identity mapping**, because: matches are
  confidence-scored and method-labelled (i.e. some are fuzzy, not exact);
  **no NCAA game-ID column was observed**; and 2027-season coverage is
  unverified. Until a crosswalk admission of its own verifies coverage and
  exact-match rates, all cross-source joins are `IDENTITY_UNVERIFIED`.
- **No mappings are invented here.** Name-only joins are refused, always.
- The `kp_*` identifier columns are identifier strings inside a provider
  file; they do **not** admit KenPom data. **KenPom is NOT ADMITTED**
  (paid; owner ruling) and `kp_*` columns may not be used to fetch or join
  KenPom data products.

## 5. Illinois college exclusion (requirement, recorded here)

CBB modeling scope **excludes Illinois college teams** (college only;
Illinois professional teams in other sports are in scope). Any consumer of
this substrate must, before any research pricing or model output, map both
teams of a fixture through an admitted **ID-based** exclusion registry
(the substrate's ESPN team IDs are the natural key) and block the fixture
if either school is an Illinois college — fail-closed: missing or
ambiguous identity is `BLOCKED`. A name-string scan is not a check and is
never evidence of compliance.

## 6. Refusals

`SOURCE_UNAVAILABLE`, `ASSET_MISSING` (tag/asset not found),
`SIZE_MISMATCH`, `SOURCE_CHANGED_AFTER_SNAPSHOT` (hash drift vs manifest),
`SCHEMA_INVALID`, `IDENTITY_UNVERIFIED` (any join without an admitted
crosswalk), `ILLINOIS_COLLEGE_BLOCKED`, `SLATE_NOT_ADMITTED` (any attempt
to treat the preliminary schedule file as a slate).

## 7. What this admission does NOT do

- No CBB engine, preregistration, freeze, or forward clock is created; no
  threshold changes. Backtests on this substrate are **design evidence
  only** — seasons a construction was designed against can never later be
  presented as untouched validation.
- Verification accrues **forward only**, from admitted pregame captures,
  under a family's own preregistration. PAPER / research only: 0u, no
  staking, no wager execution.

## 8. Owner / reviewer decisions still required

1. Accept this DESIGN-only admission (merge of this PR after Rocky review).
2. Separately: a crosswalk admission (coverage + exact-match verification
   for ESPN ↔ Torvik ↔ NCAA, incl. a 2027 file when published).
3. Separately: a schema-verified player-box successor manifest (working
   parquet reader), before any player-prop design work consumes box data.
