# PREREGISTRATION — NBA Player Props Forward Test V2 (Source Amendment)

**Status: FINAL-CANDIDATE — NOT FROZEN.** Prepared 2026-10-26 under
owner ruling (Isaac, Oct 26, 2026): *"NBA props — approve the source
amendment. Admit the replacement source prospectively, provided its
provenance, timestamps, schema, coverage, and reproducibility are
documented and tested. Keep research rows separate. No counted rows
until the amended preregistration is frozen and the source checks
pass."* Continued preparation authorized by the owner's Oct 26, 2026
ruling accepting this draft for preparation with the freeze HELD:
the freeze executes only when the owner verifies the four §12
conditions satisfied. This text is the final candidate for that
freeze; its sha256 is recorded in the evaluator pin registry on the
prepared branch (§12, condition 1) and is recorded in
`SPEC_HASHES.txt` at freeze.

This draft changes nothing until the owner freezes it (§12). It does
not edit, thaw, or re-open the frozen V1 document. No row counts under
this document before its freeze.

- Document: `PREREG_NBA_PROPS_FORWARD_V2` (source amendment)
- Supersedes by reference, for store discipline only:
  `research/nba_props_forward_20261020/PREREG_NBA_PROPS_FORWARD_V1.md`
  (frozen 2026-10-20; sha256
  `54363908b1e2332a57af9b9263ac2f398438c81b2d366442b80667086657bc79`)
- Engine under test: `NBA_PROP_EMPIRICAL_V1`
  (`sportsedge/nba_prop_empirical.py`), priced on cards by
  `sportsedge/nba_phone_prop_pricing.py` — **unchanged** by this
  amendment. The engine version named in V1's header remains the
  engine version under test here.
- Families in scope: identical to V1 §2 — `player_points`,
  `player_rebounds`, `player_assists`, `player_pra`.
  REGISTERED_RESEARCH_ONLY / NOT_VALIDATED; eligible False,
  promotable False. PLAY remains impossible under this test.

---

## 1. Why this document exists

V1 §3 admits model inputs "over the sportsdataverse box-score history
the operator supplied" — concretely, the operator store built by
`scripts/pull_nba_results.py` from the sportsdataverse
`nba_stats_player_boxscores` release asset
(`player_boxscores_2027.csv` for the 2026-27 season).

**That asset does not publish a 2026-27 file.** Verified 2026-10-26:
the pull URL returns HTTP 404 on repeated attempts; the release
(updated 2026-10-01T13:01:23Z) contains season files only through
`player_boxscores_2026.csv` (2025-26). The store V1 admits therefore
cannot exist this season, V1's clock can never produce a counted row,
and every priced board under V1 discipline fails closed
`NBA_PROP_HISTORY_STORE_UNAVAILABLE` (observed: 1,142 of 1,142 side
rows on the Oct 21, 2026 board).

V1 §10 (version rule) governs the remedy: *"Any change to the engine,
the store discipline, or this scoring after the freeze is a **new
version** scored only from that point forward, under a new versioned
document."* The Oct 21, 2026 V2 source-admission design states the
same constraint: *"Do not inject a newly scraped or differently
sourced store into V1."*

This document is that new version. It changes **one thing**: the
admitted box-score history source and its store discipline (§3–§8
below). Every other V1 term — markets (§2), slate/counting floors
(§4), row rules (§5), CLV (§6), close validity (§7), missing-CLV
codes (§8), verdict rules (§9), inference discipline (§10) — is
carried into V2 **unchanged, by reference**, and is restated only
where the source change touches it.

V1 remains frozen and in force on its own terms. V1 counted zero
rows (its admitted store never existed); there is nothing to inherit,
merge, or reconcile. V2 counting starts at zero (§10).

---

## 2. The admitted source (exact)

V2 admits exactly one box-score history source, with one named
supplement drawn from the same underlying data:

### 2.1 Primary asset — hoopR ESPN player box scores (sportsdataverse)

- **Asset:** `player_box_2027.csv` (2026-27 season file) of the
  `espn_nba_player_boxscores` release of the sportsdataverse-data
  repository.
- **URL:**
  `https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_nba_player_boxscores/player_box_2027.csv`
- **Publisher / provenance:** published by the sportsdataverse
  project (hoopR) as a GitHub release asset; the data originates from
  ESPN — rows carry **ESPN game IDs and ESPN athlete IDs**, a
  per-row `game_date`, and `athlete_position_abbreviation`. It is
  identified as an ESPN-derived asset, not an NBA-operated feed.
- **Access route:** unauthenticated HTTPS GET of the release asset.
  No account, cookie, or credential is involved or recorded.
- **Fields consumed:** `athlete_id`, `athlete_display_name`,
  `team_abbreviation`, `game_id`, `game_date`, `minutes`, `points`,
  `rebounds`, `assists`, `athlete_position_abbreviation` (fallback
  position source only, §7.3).

### 2.2 Supplement — ESPN summary API (same underlying ESPN data)

Admitted **only** for games the primary asset has not yet ingested at
store-build time (the asset updates on the publisher's schedule and
lags late slates):

- **URL pattern:**
  `https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event=<ESPN event id>`
- One request per missing game; the stat-column label order
  (MIN/PTS/FG/3PT/FT/REB/AST/…) is read from each response, never
  assumed. Each supplemented game is listed in the build manifest
  with its event ID and retrieval timestamp (§4).

### 2.3 Schedule authority / cross-check source

- **ESPN scoreboard API:**
  `https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=YYYYMMDD`
  is the schedule authority for game dates and the cross-check every
  build must pass (§9, check S2). It supplies no store rows.

### 2.4 Positions source

- **ESPN team rosters API:**
  `https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams`
  then `/teams/<id>/roster` for all 30 teams, pulled per slate under
  the discipline of §7.3.

### 2.5 Explicitly not admitted

- The V1 asset (`nba_stats_player_boxscores`) remains V1's source. It
  is not a V2 source, fallback, or supplement.
- The NBA.com CDN box-score feed (Candidate A of the Oct 21 design)
  is **not** admitted by this amendment. Admitting it — or any other
  source — is a further versioned document, not an edit to this one.
- No source may be mixed into a store build without being named in
  the build manifest (§4). An unnamed source in a build voids that
  build for counting.

---

## 3. Provenance — the Oct 26, 2026 research store

The store that motivated this amendment was assembled 2026-10-26
(retrieval window 10:48–10:53 UTC) by `build_store.py`, with a proof
driver (`proof_driver.py`, results in `proof_results.json`). Full
record:
`~/workspace/goals/nba-readiness-and-backtest-harness/hidden_files/nba_prop_store_20261026/PROVENANCE.md`.
Summary:

- **Primary asset pull:** retrieved 2026-10-26T10:50:21–10:50:22 UTC;
  506,411 bytes; sha256
  `688cea0272e725ee425ec11b1432a7ba738281883e827b47069ade0d2feee397`;
  release asset `updated_at` 2026-10-25T12:14:37Z. Contained 995
  player rows over 36 games, 2026-10-20 → 2026-10-24 (the Oct 25
  games tipped after its update time).
- **Supplement:** the 7 Oct 25 games (ESPN event IDs 401909861–
  401909867) pulled from the summary API 2026-10-26 ~10:51 UTC; 196
  player rows.
- **Game dates:** from the asset's own `game_date` (36 games) and
  2026-10-25 for the supplement; **cross-checked against the ESPN
  scoreboard for 20261020–20261025: 43/43 game IDs match, 0 date
  mismatches.**
- **Positions:** ESPN rosters for all 30 teams, retrieved
  2026-10-26T10:51:49 UTC (518 athletes). Of the 446 store players:
  443 positions from those rosters, 2 from the player's most recent
  box-score `athlete_position_abbreviation`, 1 (Michael Ajayi, ESPN
  id 5176517) with no position anywhere — no `positions.csv` row; his
  single DNP row is excluded `excluded_no_position` and he has 0
  played games, so there is no pricing effect.
- **Supplement integrity:** the supplement's summed player PTS
  reproduce the recorded final team scores for all 14 teams of the
  Oct 25 slate exactly; a hoopR spot-check (game 401909853) sums to
  MIA 110 / CHA 115, matching the scoreboard final.
- **Loader receipt on this store:** `NBA_PROP_STORE_LOADED` —
  records_in 1,191; records_kept 967; excluded_dnp_minutes0 223;
  excluded_no_position 1; excluded_no_date 0; excluded_invalid 0;
  players 398 (446 distinct players appear; 48 are DNP-only).
- **Store file hashes (sha256, computed 2026-10-26):**
  - `nba_player_games_2026-27.csv` —
    `a993d05f533801434131b867bfd9aae7dd3d8e699bf044815e265ef42317e3c0`
  - `game_dates.csv` —
    `b683deeba169b491a3c3d6e9f8ae06f32fb6e5a75177644af978a921d3a84b30`
  - `positions.csv` —
    `d097786a15ba6618214d38f997feffed2d4b2f08a41eb85184e5648527efcb28`

**Honest limits (binding on how this store may be used):**

1. **Positions are an Oct 26, 2026 snapshot.** Using this store for
   target dates before the roster pull would leak present-day
   positions into past targets. This store is therefore a
   **research store only**; it can never supply counted rows, for any
   date. Counted rows require a per-slate store built under §7.3.
2. This store's proof runs (§9) demonstrate the data blocker is
   removed. They price **zero** rows — correctly: the carried-over
   sufficiency gate (§7.4) cannot be met by any player yet (league
   max 4 prior played games at a 2026-10-26 target).

---

## 4. Hash-pinning procedure (executed at freeze, repeated per build)

The primary asset is a living release file: its bytes change as the
publisher ingests games. A single permanent hash pin is therefore
impossible and is **not** what this amendment pins. What is pinned is
the asset's **identity** (§2.1) plus this procedure:

**Mechanism (prepared 2026-10-26):** `slate_build.py` (sibling of the
research builder in the store directory) implements this section: it
archives the raw bytes of every fetched response (asset, scoreboard
cross-checks, supplements, roster pull) beside the built store and
writes the build manifest of §4.2 automatically. Its companion
re-verifier `verify_slate_build` re-reads a finished build and
classifies it fail-closed: missing raw bytes, a manifest/store hash
mismatch, missing manifest fields, or a roster pull after the
permitted cutoff each force RESEARCH_ONLY with the defect named —
never a crash, never a counted build. Proven by the dry runs of
§9.1.

1. **At freeze:** download the primary asset fresh. Record in the
   freeze record: URL, retrieval timestamp (UTC), byte size, release
   asset `updated_at`, and sha256 of the raw bytes. Archive the raw
   bytes unaltered in the records location named at freeze (§12).
2. **At every store build** (research or counted): produce a build
   manifest recording — primary asset URL, `fetched_at` (UTC), byte
   size, `updated_at`, sha256 of raw bytes; every supplemented game
   (ESPN event ID, retrieval timestamp); the roster pull timestamp;
   and the sha256 of each of the three emitted store files. The
   manifest is saved beside the store snapshot it describes.
3. **For a counted slate:** the manifest and the store snapshot used
   for pricing are archived in the records location **before** the
   slate's rows are scored. A slate whose manifest is missing, or
   whose store-file hashes do not match the manifest, contributes
   **zero** counted rows (fail closed; the slate is recorded as a
   store-discipline failure, not silently repaired after the fact).
4. Raw response bytes for supplemented games and the roster pull are
   archived with the manifest for counted slates.

---

## 5. Store schema (exact)

A store is a directory named by the environment variable
`SPORTSEDGE_NBA_PROP_STORE_DIR`, containing exactly these files. The
loader (`sportsedge/nba_phone_prop_pricing.py::load_store_from_dir`)
re-reads the directory on every batch; a store snapshot is therefore
identified by its build manifest (§4), not by the directory.

### 5.1 `nba_player_games_*.csv` (one or more files; pull shape)

| Column | Type | Meaning |
|---|---|---|
| `PLAYER_ID` | int | ESPN athlete ID |
| `PLAYER_NAME` | string | Full player name as in the source |
| `TEAM_ABBREVIATION` | string | ESPN team tricode |
| `GAME_ID` | int | ESPN event ID |
| `MIN` | float | Minutes played; **0 = did-not-play** |
| `PTS` | int | Points (0 for DNP rows) |
| `REB` | int | Total rebounds (0 for DNP rows) |
| `AST` | int | Assists (0 for DNP rows) |
| `SEASON` | string | `2026-27` |
| `SEASON_TYPE_ID` | int | 2 = regular season |

Source DNP rows (empty minutes/stats in the asset) are emitted as
MIN=0 / PTS=REB=AST=0 — the did-not-play representation the engine
excludes by rule. The loader-required subset is
PLAYER_ID / PLAYER_NAME / GAME_ID / MIN / PTS / REB / AST.

### 5.2 `game_dates.csv`

| Column | Type | Meaning |
|---|---|---|
| `GAME_ID` | int | ESPN event ID |
| `GAME_DATE` | date | Calendar date of the game (YYYY-MM-DD), cross-checked against the scoreboard authority (§2.3) |

A player-game row whose game has no date is dropped
(`excluded_no_date`). The engine's prior-game logic is date-granular
(§7.1); a wrong date is a point-in-time error, which is why the
cross-check is a counting gate (§9, S2), not a courtesy.

### 5.3 `positions.csv`

| Column | Type | Meaning |
|---|---|---|
| `PLAYER_ID` | int | ESPN athlete ID |
| `POSITION` | string | Single letter `G` / `F` / `C` (compound source values resolve by first character in the loader) |

A player with no position row is outside the engine universe
(`excluded_no_position`). Positions are never inferred from name,
minutes, or a later roster (§7.3).

### 5.4 Loader contract and refusal codes

- **Receipt:** a successful load attaches
  `NBA_PROP_STORE_LOADED` with counters: `players`, `records_in`,
  `records_kept`, `excluded_dnp_minutes0`, `excluded_no_position`,
  `excluded_no_date`, `excluded_invalid`, plus `engine_id` =
  `NBA_PROP_EMPIRICAL_V1` and the pull-file list.
- **Fail closed:** if any of the three files is missing or empty,
  every row of the batch fails
  `NBA_PROP_HISTORY_STORE_UNAVAILABLE`. There is no partial-store
  pricing.
- **Row-level refusals (pricing lane, `nba_phone_prop_pricing.py`):**
  `NBA_PROP_PLAYER_NOT_IN_STORE`, `NBA_PROP_PLAYER_IDENTITY_MISSING`,
  `NBA_PROP_PLAYER_IDENTITY_AMBIGUOUS`, `NBA_PROP_LINE_MISSING`,
  `NBA_PROP_QUOTE_PRICE_MISSING`, `NBA_PROP_SIDE_UNVERIFIED`,
  `NBA_PROP_TARGET_DATE_UNVERIFIED`, `NBA_PROP_MARKET_NOT_SUPPORTED`.
- **Row-level refusals (engine, `nba_prop_empirical.py`):**
  `NBA_PROP_INSUFFICIENT_PRIOR_GAMES`, `NBA_PROP_PLAYER_NOT_IN_STORE`,
  `NBA_PROP_POOL_UNAVAILABLE`, `NBA_PROP_POSITION_GROUP_UNVERIFIED`,
  `NBA_PROP_STAT_UNSUPPORTED`, `NBA_PROP_LINE_INVALID`.
- **Evaluator refusal (carried from V1 §2):** an out-of-scope row
  reaching the evaluator is refused `MARKET_OUT_OF_SCOPE` and
  excluded from inference.

---

## 6. Coverage

- **Demonstrated (research store, Oct 26, 2026):** 43 of 43
  ESPN-scheduled games for 2026-10-20 → 2026-10-25, by date:
  Oct 20: 3 · Oct 21: 11 · Oct 22: 2 · Oct 23: 12 · Oct 24: 8 ·
  Oct 25: 7. Zero gaps. (Oct 23 is a 12-game slate; the "11" seen in
  one DK fanout file is that file's split, not a missing game.)
- **Forward obligation (counted slates):** for each slate date, the
  per-slate store must cover **every** ESPN-scheduled game strictly
  before the slate date in the 2026-27 regular season — priors are a
  player's full same-season history, so a missing earlier game is a
  silent prior corruption, not a local gap. The scoreboard
  cross-check (§9, S2) is run over the store's full date range at
  each counted build, and any missing game fails the build for
  counting (research use may continue, labeled).

---

## 7. Timestamps and point-in-time discipline

### 7.1 Record timestamps

The engine is date-granular: a player-game record is usable for a
target game only if its `GAME_DATE` is **strictly before** the target
game's calendar date. Records carry no intra-day timestamp and none
is fabricated; same-date games never serve as priors for each other.
Build-level timestamps (asset retrieval, supplement retrievals,
roster pull — all UTC) live in the build manifest (§4) and establish
that the store was built from information available at build time.

### 7.2 DNP discipline

Rows with MIN = 0 are did-not-play and are excluded everywhere
(enforced in the loader counters). They remain in the file so the
exclusion is auditable.

### 7.3 Positions discipline (per-slate refresh — binding for counted rows)

1. The store used to price a counted slate is **rebuilt for that
   slate**: fresh primary-asset pull, supplements for any uningested
   games, and a **fresh roster pull**.
2. The roster pull must be timestamped **on or before the slate's
   pricing time and not after the slate date**. Positions are "as of
   the slate date" only under this rule. A store whose positions were
   pulled after the slate date can never price counted rows for that
   slate — no exceptions, no retroactive repair.
3. A player on no current roster at pull time takes his position
   from his most recent box-score `athlete_position_abbreviation`
   **on or before the slate date**; a player with no position from
   either route is excluded (`excluded_no_position`), never guessed.
4. The Oct 26 research store (§3) satisfies none of this for any
   slate and is research-only by construction.

### 7.4 Sufficiency gate (carried from V1, unchanged)

A player prices only with **≥ 10 prior same-season games with
minutes > 0, strictly before the target game's calendar date**
(`MIN_PRIOR_GAMES = 10` in `nba_prop_empirical.py`), and rows carry
the engine stamp per V1 §5 (`engine_id`, `sufficiency_met`,
`n_prior` ≥ 10, pool source, store provenance, declared
participation limitation). Position pools need ≥ 30 games else the
league pool is used — engine behavior, unchanged. Consequence:
league max prior count is 4 at a 2026-10-26 target, so the first
countable **priced** rows cannot exist before roughly mid-November
2026, when players reach their 11th game. The freeze does not need
to wait for that; counting does.

---

## 8. Reproducibility

- **Mechanism:** `build_store.py` (research store directory, §3) is
  the one-off builder that assembled the Oct 26 research store. The
  repeatable per-slate builder is `slate_build.py` (same directory):
  same admitted inputs → the same three store files, plus the raw
  archive and build manifest of §4. The loader re-reads the store
  directory per batch, so a rebuild takes effect without code
  change.
- **Code identity:** the builder, the loader, and the engine are
  identified at freeze by repository path and commit. Any change to
  `build_store.py`'s transformation rules after the freeze is a
  store-discipline change under V1 §10 — a new version, not an edit.
- **Proof artifacts:** every counted build saves its proof run
  (loader receipt + per-board blocker counts, in the shape of
  `proof_results.json`) with the build manifest (§4.3).

---

## 9. Source checks — all must pass before any counted row

For the **first counted slate**, all of S1–S6 pass on that slate's
own per-slate store. For **every subsequent counted slate**, S1, S2,
S3, and S6 pass on that slate's store; S4 and S5 are standing
properties re-verified whenever the builder, loader, or engine code
changes. A failed check means the slate contributes zero counted
rows; the failure is recorded, not routed around.

| # | Check | Pass criterion |
|---|---|---|
| S1 | **Loader receipt on a real board** | Pricing a real captured board against the slate's store attaches `NBA_PROP_STORE_LOADED` and yields **0** rows blocked `NBA_PROP_HISTORY_STORE_UNAVAILABLE`. (Rows refusing on sufficiency or identity are substantive outcomes, not failures.) |
| S2 | **Scoreboard cross-check** | Every game in the store's `game_dates.csv` matches the ESPN scoreboard for its date (ID + date), **0 mismatches**, and every scheduled game in the store's date range is present (§6). |
| S3 | **Positions-as-of-slate** | Build manifest's roster-pull timestamp satisfies §7.3.2 for the slate date; every priced player has a position from the pull or the §7.3.3 fallback; exclusions are counted, not silent. |
| S4 | **Internal consistency** | Distinct GAME_IDs in the player file = rows in `game_dates.csv`; per-date game counts equal the scoreboard's; DNP rows are MIN=0 with zeroed stats. |
| S5 | **Supplement integrity** (when a supplement was used) | Each supplemented game's summed player PTS equals the recorded final team score for **both** teams. |
| S6 | **Proof artifacts saved** | Loader receipt, blocker counts, build manifest, and store-file hashes for the slate's store are archived in the records location before scoring (§4.3). |

### 9.1 Check results against the Oct 26 research store (run 2026-10-26)

These results qualify the **source and the build mechanism**. They do
not qualify any slate for counting — the Oct 26 store is
research-only (§3, §7.3.4), and S3 cannot pass for it by
construction.

- **S1 — PASS (re-run 2026-10-26 by the drafting agent).** Proof
  driver re-run against fresh origin/main code (12dc31a03): Run A
  (Oct 21 RAW_BOARD, 1,142 side rows — the board that went
  1,142/1,142 store-blocked under V1's impossible store): receipt
  `NBA_PROP_STORE_LOADED`, **0 store-blocked**, 1,130 ×
  `NBA_PROP_INSUFFICIENT_PRIOR_GAMES`, 12 ×
  `NBA_PROP_PLAYER_NOT_IN_STORE`, 0 priced. Run B (Oct 25 PM
  captures, 582 side rows): **0 store-blocked**, 556 ×
  `NBA_PROP_INSUFFICIENT_PRIOR_GAMES`, 26 ×
  `NBA_PROP_PLAYER_NOT_IN_STORE`, 0 priced. Counts identical to the
  saved `proof_results.json`. Log:
  `proof_rerun_20261026_v2draft.log` beside the store.
- **S2 — PASS (from saved build artifacts).** 43/43 game IDs match
  the ESPN scoreboard for 20261020–20261025, 0 date mismatches
  (retrieved 2026-10-26 ~10:49 UTC; recorded in PROVENANCE.md). Not
  re-fetched during drafting.
- **S3 — NOT SATISFIABLE for the Oct 26 store (by design).**
  Positions are an Oct 26 snapshot with no slate to be as-of for;
  the per-slate discipline (§7.3) has never yet been executed for a
  counted slate because none exists. First test is the first counted
  slate's build.
- **S4 — PASS (re-counted 2026-10-26).** Player file: 1,191 rows,
  43 distinct GAME_IDs = 43 rows in `game_dates.csv`; per-date
  counts 3/11/2/12/8/7; DNP exclusions counted by the loader (223).
- **S5 — PASS (from saved build artifacts).** Supplement game sums
  reproduce the recorded finals for 14/14 teams (PROVENANCE.md).
- **S6 — PASS for the research build.** `proof_results.json`,
  PROVENANCE.md (with asset hash, byte size, retrieval times), and
  the re-run log are saved beside the store. **Partial gap:** the
  raw primary-asset bytes and raw supplement responses were not
  archived at build time — §4.1/§4.4 require archiving from the
  freeze forward; this is a freeze-checklist item (§12), not a
  defect in the research store.

### 9.2 Per-slate machinery dry runs (executed 2026-10-26)

The §4/§7.3 machinery (`slate_build.py`) was dry-run end-to-end
against live admitted sources. Both builds are RESEARCH_ONLY; the
point proven is the archiving, manifest, and gate mechanics — not
counting, which the held freeze forbids.

- **Retroactive slate (2026-10-25, pricing time 2026-10-25T15:22
  −05:00, the Oct 25 PM capture instant):** history Oct 20–24 built
  (36 games, 995 rows); S2 PASS, S4 PASS; **positions gate
  FAIL_CLOSED** (`ROSTER_PULL_AFTER_PRICING_TIME`,
  `ROSTER_PULL_AFTER_SLATE_DATE` — the roster pull of 2026-10-26
  12:06 UTC postdates the slate's pricing time by construction);
  classification RESEARCH_ONLY. Loader proof against this store:
  receipt `NBA_PROP_STORE_LOADED`, **0 store-blocked**; Run A (Oct 21
  board) counts identical to §9.1's S1 (1,130 / 12); Run B (Oct 25
  PM) 554 / 28 vs 556 / 26 — a proof-driver name-resolution
  difference only, reproduced and bounded in §9.3: exactly two
  side rows differ — the OVER/UNDER rows of one capture entry,
  token 'Black' (ORL@NYK points), resolving solely via a player
  whose only store presence is the slate-date game itself,
  absent from a history-truncated store by construction.
- **Prospective slate (2026-10-26, pricing time 2026-10-26T12:00
  −05:00):** full history Oct 20–25 built from the live asset
  (43 games, 1,191 rows — the asset had ingested Oct 25 natively;
  no supplement was needed); S2 PASS, S4 PASS; **positions gate
  PASS** (roster pull 2026-10-26 12:07 UTC ≤ pricing time, on the
  slate date); classification still RESEARCH_ONLY — research mode
  was requested, and counting additionally requires the freeze.
- Raw bytes for every fetch in both builds are archived under each
  build's `raw/` directory with URL, retrieval timestamp, byte count
  and sha256 in its `build_manifest.json` (primary asset sha256
  `7aa174d4a3a0c17f23c9fd868a4d7131b44418c5d39a059ea505ef3eaf5082d1`,
  2026-10-26 pull — the asset is living, so this differs from §3's
  earlier pull, as §4 anticipates). The summary-supplement fetch
  path did not trigger in either build (the asset covered every
  in-range game); the supplement transform is the same code that
  produced the S5-verified Oct 25 supplement in §3. The
  unexercised path is covered by a deterministic fixture
  regression, and the machinery's supplement failure handling was
  completed, in §9.3.

### 9.3 Review-checklist closure (owner's disposition, 2026-10-26)

Two items from the independent-review checklist, closed with
evidence on branch `feat/nba-props-v2-evaluator-20261026`
(tests: `tests/test_nba_props_v2_review_items_20261026.py` in the
repo; the machinery-local copies live beside `slate_build.py` in
its `test_slate_build.py`):

1. **Run B two-row discrepancy — reproduced and bounded.** Both
   count pairs reproduce from the saved artifacts under one
   parameterized code path (Run A identical on both stores:
   1,130 / 12; both Run B runs emit 582 outputs for 582 inputs).
   A row-by-row diff of the two Run B outputs differs in
   EXACTLY two rows: the OVER and UNDER rows of the single
   ORL@NYK points entry for capture token 'Black' (line 8.5). In
   the full store the token resolves to Anthony Black
   (PLAYER_ID 4712849, ORL), whose sole store presence is game
   401909863 on 2026-10-25 — the slate game itself — with 0 prior
   games strictly before that date (engine probe: refusal with
   `n_prior = 0`). In the truncated store he is absent by
   construction. (The other store Black, Leaky Black of SAC, is
   team-filtered out of this fixture in both stores and plays no
   part.) Consequences, each test-pinned: (a) **counted
   eligibility cannot change** — pricing the two rows four ways
   (raw token vs the truncated store; force-resolved name vs the
   truncated store; vs the full store; vs a store whose history
   includes the slate game) refuses them every time
   (`PLAYER_NOT_IN_STORE` or `INSUFFICIENT_PRIOR_GAMES` with
   `n_prior = 0`), because a counted build's history is
   [season start, slate date) and a player resolvable only
   through a slate-date game has zero priors under any
   resolution; (b) **no silent drop** — every unresolved capture
   name appears as explicit `PLAYER_NOT_IN_STORE` refusal rows
   (2 per unresolved entry), and those are all the
   not-in-store rows in each run.
2. **Supplement fetch path — deterministic regression.** The
   path did not trigger in either live dry run (§9.2). It is now
   covered by recorded-fixture tests (the fixture summary is
   SYNTHETIC, built to the transform's expected schema — no
   recorded Oct 25 summary response survives in the workspace):
   an asset-missing scheduled game is supplemented, its raw
   bytes archived with a manifest entry (URL, fetched_at, bytes,
   sha256) like every other fetch, and its rows enter the store
   with the correct game/date attribution (DNP rows zeroed).
   Machinery change (minimal, in `slate_build.py`): a supplement
   that could not be fetched or parsed previously aborted the
   build; it now fails closed per game — the failure is recorded
   in the manifest (`supplement_failures`), any partially added
   rows are rolled back, fetched bytes stay archived marked
   `UNPARSEABLE_SUPPLEMENT`, and the missing game fails S2,
   which fails the positions gate and classifies the build
   RESEARCH_ONLY. Tests pin all three failure shapes (missing,
   malformed JSON, structurally broken) plus the verification
   leg: supplement archive bytes tampered after the build fail
   `verify_slate_build` closed (`RAW_HASH_MISMATCH` /
   `RAW_SIZE_MISMATCH` → RESEARCH_ONLY).

---

## 10. Separation — research rows vs counted rows; no backfill

- **V1 is untouched.** Its text, freeze, and (empty) record stand.
  Nothing in this document re-opens, extends, or inherits V1's
  clock, and V1's first-countable-slate boundary (Oct 21, 2026) has
  no meaning under V2.
- **V2 counting starts at zero** at this document's freeze. The
  first countable slate is the first slate priced **after** the
  freeze timestamp with a per-slate store passing §9. Rows from
  games on or before the freeze date never count, however they were
  produced (V1 §4 boundary discipline, carried).
- **Research rows:** any row priced before the freeze, or priced
  with the Oct 26 research store, or priced with a store failing any
  §9 check, is a research row. Research rows are labeled as research
  (never with the V2 prereg identity), are kept in separate records
  from counted rows, and are never promoted into V2 counters
  retroactively.
- **No backfill:** no pre-freeze slate, V1-era slate, or
  research-priced slate may be re-scored as counted under V2, even
  if a compliant store for its date is later built. (For pre-freeze
  dates a compliant store is in any case impossible: positions
  as-of a past date cannot be pulled after the fact, §7.3.2.)
- **The October 26, 2026 store is permanently research-only for
  historical slates.** It admits no retrospective counting — not
  now, and not if later checks pass — because its positions were
  retrieved after those slates' pricing times; the Oct 25, 2026 dry
  run (§9.2) demonstrates its per-slate build failing the §7.3 gate
  closed for exactly that reason. Its rows may be used for research
  only, labeled as research, forever.
- **Verdict floors (carried from V1 §4):** no verdict review before
  **all** of: 4 full slates AND at least 50 rows AND exactly 40
  distinct games **per market**; any market under 100 rows at
  scoring time stays `INSUFFICIENT_SAMPLE`; the §8
  insufficient-close rule (>20% `CLV_MISSING` →
  `INSUFFICIENT_CLOSE_DATA`) applies unchanged.

---

## 11. Carried V1 terms (by reference, unchanged)

V1 §2 (markets in scope; PRA only where combo lines were captured),
§3's capture discipline (scoring uses exclusively the capture
program's committed DK records; every row carries the §3 fields; no
fabricated or retroactive prices), §5 (row construction; PICKED /
PASSED definitions), §6 (CLV definition — primary metric), §7
(close-capture validity, 60-minute rule), §8 (missing-CLV reason
codes), §9 (verdict rules per market, incl. the calibration leg and
its settlement source), §10 (game-clustered intervals; no interim
verdicts; one review at the first qualifying scoring), and §11 (what
the test does not do — no PLAY, no staking, no registration change)
apply to V2 exactly as written in the frozen V1 text. Where V1 §3
names the operator-supplied sportsdataverse history as the model
input, read instead: **the V2 admitted source of §2 of this
document, under the discipline of §§4–8 of this document.** That
substitution is the entirety of the amendment.

The engine's declared limitation stands: no participation,
minutes-projection, or availability feed. It is declared on every
priced row and is part of what this test measures; it is never
repaired inside the test window.

---

## 12. Freeze gate — the owner's four conditions

The freeze is the owner's act, HELD by his Oct 26, 2026 ruling until
he verifies all four conditions satisfied. Before V2 counts a single
row, **all four** must hold:

1. **Evaluator pin + separation.** The evaluator pin is updated to
   the exact sha256 of this document's final text, with explicit
   V1/V2 and research/counted separation: a V2 verdict is computed
   only over V2 counted rows; V1 rows and research rows are reported
   separately and never blended in.
   *Mechanism (PREPARED 2026-10-26, branch
   `feat/nba-props-v2-evaluator-20261026`, not merged):* the
   evaluator's pin registry pins this final-candidate text's sha256
   alongside V1's untouched pin (the registry line is appended to
   `SPEC_HASHES.txt`; the V2 family configs carry the same hash; a
   tampered document fails the pin closed), and the evaluator
   partitions rows by declared prereg identity and counting class
   before scoring, stamping the verdict record with the counted
   rows' provenance. *Status: prepared and tested; takes effect
   when the branch merges and the frozen text is this text.*
2. **Per-slate raw archiving.** For each eligible slate: raw source
   bytes, SHA-256, retrieval timestamp, and provenance are archived
   with the slate's build.
   *Mechanism (PREPARED + PROVEN 2026-10-26):* `slate_build.py`
   (§4) archives every fetch's raw bytes with its manifest entry,
   and `verify_slate_build` fails any defective build closed to
   RESEARCH_ONLY (§9.2 dry runs). The supplement fetch path —
   unexercised in the live dry runs — is covered by a
   deterministic fixture regression with fail-closed supplement
   handling (§9.3). *Status: machinery proven;
   satisfied per slate at that slate's counted build, from the
   first counted slate forward. The Oct 26 research build's missing
   raw bytes (§9.1, S6) are historical and unrepairable — one more
   reason that store can never count (§10).*
3. **Committed text, immutable asset pin, first slate named.** The
   final V2 text is committed (proposed location:
   `research/nba_props_forward_20261020/PREREG_NBA_PROPS_FORWARD_V2.md`,
   beside V1, its sha256 recorded in that directory's
   `SPEC_HASHES.txt`); the freeze-time asset pin of §4.1 is executed
   (fresh download; URL, retrieval timestamp, byte size,
   `updated_at`, sha256 recorded; raw bytes archived in the named
   records location); and the first prospective counted slate is
   explicitly named in the freeze record.
   *Status: OPEN — these are freeze-time owner acts; none has been
   done, and no preparation in this document does them.*
4. **First slate's positions check passed before pricing.** The
   first counted slate's per-slate build passes the §7.3
   positions-as-of-slate check (check S3) before that slate is
   priced, with S1–S6 green on that slate's store.
   *Mechanism (PREPARED + PROVEN 2026-10-26):* the S3 gate inside
   `slate_build.py`, demonstrated FAIL_CLOSED on a retroactive slate
   and PASS on a prospective one (§9.2). *Status: OPEN — the check
   is an event at the first counted slate's build; it cannot be
   satisfied in advance, and its failure that day means that slate
   contributes zero counted rows.*

Supporting freeze-time recordings (owner, at the same act): the
builder (`slate_build.py`) identified by path + commit hash in the
freeze record; the records location named for V2 build manifests,
store snapshots, proof artifacts, and priced-row records (proposed:
the goal workspace's records area until a repo records branch is
named at freeze). Priced counted rows additionally await the §7.4
sufficiency wall (~mid-November 2026) regardless of freeze date.

*Drafted 2026-10-26. Modeled on the frozen V1 preregistration's
discipline and on the Oct 21, 2026 V2 in-season source-admission
design (whose "do not inject into V1" rule this document honors).
Prepared under Isaac's Oct 26, 2026 source-amendment ruling; freeze
is the owner's act alone.*
