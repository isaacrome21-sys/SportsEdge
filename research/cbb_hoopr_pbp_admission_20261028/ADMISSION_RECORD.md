# Admission record — hoopR MBB play-by-play (load_mbb_pbp family), seasons 2015–2023, for the CBB first-half (1H) design screen

**Status: SAMPLE-VERIFIED / ADMISSION PROPOSED — DESIGN ONLY — NOT VALIDATION —
NO FORWARD-CLOCK CREDIT — NO PLAY ELIGIBILITY.**
Prepared 2026-10-28 (pull 2026-10-28T15:12:08Z–15:55:33Z) for independent review.
Admission takes effect only if this PR is merged after independent (Rocky)
review, and even then the source is a **design-screen input only**, scoped to
deriving first-half team points for the CBB first-half (1H) family.

**Purpose — the unblock this record exists for.** The CBB first-half design
(`research/nba_cbb_activation_20261028/CBB_TEAM_TOTALS_1H_DESIGN.md` §2,
PR #2843) names one prerequisite before 1H is screenable: hoopR play-by-play
release assets (`load_mbb_pbp` family) pinned by the full-tuple rule of
PR #2835 **with schema verification**. PR #2835 pinned schedules and player
box (the latter on bytes + hash only) and no PBP asset; the team-totals
screen record (PR #2892, §6 of its SCREEN_REPORT) therefore recorded CBB
first-half lines **NOT_EXECUTABLE — `PBP_PREREQUISITE_MISSING`**. This record
is that PBP admission job. It does not run the 1H screen and fits no share;
it supplies the pinned, schema-verified PBP substrate the design requires.

Every factual claim carries an evidence state: **verified-by-pull**
(checked against bytes or API responses fetched from the SportsEdge
runtime) or **documented-only** (provider documentation / design text;
not reproduced here).

**Verdict: ADMITTED — exact scope: design-screen use for the CBB
first-half (1H) family only** — fitting the first-half share and
deriving 1H outcomes from the pinned bytes, under the §6
final-agreement gate — effective on merge after independent review.
No other use is admitted (§7's scope lock is binding).

## 1. Source and provenance

- **What is pinned:** ESPN-derived NCAA Division I men's basketball
  play-by-play for the seasons ending 2015–2023 (2014-15 → 2022-23, the
  CBB screens' walk-forward span), assembled by the **sportsdataverse**
  project and consumed by hoopR's `load_mbb_pbp`. Canonical route
  (verified-by-pull): GitHub release assets of
  `sportsdataverse/sportsdataverse-data`, release
  `espn_mens_college_basketball_pbp` (**release ID 97399228** — the release
  immediately adjacent to the schedules release 97399224 pinned by
  PRs #2835/#2867), assets `play_by_play_<season>.csv` for seasons
  2015–2023.
- **Route note (verified-by-pull):** the hoopR-data code repository
  (`sportsdataverse/hoopR-data`) carries no GitHub releases; the
  downloadable substrate the hoopR loaders resolve to lives in
  `sportsdataverse-data`, exactly as PR #2835 recorded for schedules.
- **Licenses (verified-by-pull, per PR #2835):** `sportsdataverse-data`
  — MIT; ESPN's own terms govern the underlying data. This repo commits
  **hashes, manifests and retrieval code only — no data files**.

## 2. The pin rule — rolling release, attestation at pull timestamp

The play-by-play release is **rolling** — assets are replaced in place
under a stable tag (all 27 in-window assets carried `updated_at`
2026-10-18 at pull time, i.e. the release had been refreshed upstream
ten days before this pull), so **a tag pins nothing**. The pin for every
asset in this manifest is the full tuple:

> **release tag + release ID + asset ID + asset size + asset
> `updated_at` + SHA-256 of the downloaded bytes**, recorded in
> `pbp_manifest.json` together with the pull timestamp
> (`retrieved_at_utc` = 2026-10-28T15:55:33Z (pull window 15:12:08Z–15:55:33Z)).

**Attestation scope, stated plainly:** because the release is rolling,
this pin attests the bytes **as pulled at that timestamp** — the
strongest attestation this source supports. It does **not** attest that
upstream bytes are stable or immutable, and no such claim is made. The
committed script `pull_hoopr_pbp.py` re-downloads every pinned asset
(streaming, hashed incrementally — a season CSV is 549–843 MB) and
compares size + SHA-256; any drift is
`SOURCE_CHANGED_AFTER_SNAPSHOT` — a **refusal**, never silent
acceptance — and a drifted asset may only re-enter through a successor
manifest with its own review. Formats are pinned independently; one
format's pin never vouches for another.

**Formats pinned and not pinned.** The CSV serialization is the pinned,
consumed route: it is the only serialization the SportsEdge runtime
(Python, stdlib) can read. The `.parquet` twin of each season exists
upstream and is **not pinned**: the runtime has no working parquet
reader (the same caveat PR #2867 recorded), so a parquet pin could
attest bytes whose content this program cannot verify or consume. The
`.rds` twin (hoopR's native R route) is likewise **not pinned** — it is
not a consumed route in this repo, the treatment PR #2867 applied to
schedule `.rds` assets. All 18 twin assets are listed with their
upstream tuples in `pbp_manifest.json` under `unpinned_twin_formats`,
recorded as present-but-not-pinned, never silently dropped.

## 3. Hash-verified pins (pulled 2026-10-28T15:12:08Z–15:55:33Z)

All nine assets are in release `espn_mens_college_basketball_pbp`
(release ID 97399228). Every downloaded byte count matched the GitHub
API's reported asset size exactly at pull time (verified-by-pull).

| Asset | Asset ID | `updated_at` | Bytes | SHA-256 |
|---|---|---|---|---|
| `play_by_play_2015.csv` | 653499288 | 2026-10-18T12:59:30Z | 721,559,218 | `4d7c5e4b65e95b7f02648e564d4ecd1c2ccb53c909c5921c32493aac43c8c4b9` |
| `play_by_play_2016.csv` | 653524040 | 2026-10-18T13:13:11Z | 751,120,016 | `b7e594b21db3aec68a3d711d2bc4e673b911f4455231419ea3f6d061c00eec7c` |
| `play_by_play_2017.csv` | 653546124 | 2026-10-18T13:26:01Z | 757,422,149 | `7362330277ddcde867ecc4fdc0b0b2a907948e639f8d834d467090ac18974e02` |
| `play_by_play_2018.csv` | 653571487 | 2026-10-18T13:37:20Z | 762,239,275 | `ff162739d5dbc4a8b403fc04c1898b95c570b2cee78d992481ebf3bc8069fe51` |
| `play_by_play_2019.csv` | 653594244 | 2026-10-18T13:48:20Z | 745,159,233 | `d0dbc3df71bfed7b4a348d21e0807fa6a8c8473e9552468f3071b861f37c9acf` |
| `play_by_play_2020.csv` | 653614708 | 2026-10-18T13:59:53Z | 725,431,155 | `affcf51e38990dfc0f83a7fc28621272c78fddfdf50093cacc48240b6542b1a9` |
| `play_by_play_2021.csv` | 653633324 | 2026-10-18T14:09:09Z | 549,267,055 | `c62b878cb915410f2c364a590bd1b3e01fea26acc79e2e6f4c8e242bcd7f7368` |
| `play_by_play_2022.csv` | 653654167 | 2026-10-18T14:19:40Z | 807,391,148 | `93e3e9aade48b93f42ba3f6233655a201f0924a375979bbb00f00e35fcb2c8d8` |
| `play_by_play_2023.csv` | 653675374 | 2026-10-18T14:30:28Z | 842,514,558 | `4ed30b0b62e87d8951f7e956fcd42b1099e85f5a38960adbdb008eeaef9dcf43` |

**Re-verification (verified-by-pull):** after the pull, every pinned
file was re-read from disk and re-hashed — 9/9 hashes reproduced
(second read). In addition the 2021 asset (smallest, 549,267,055 bytes)
was downloaded a second time in full from the release route and its
SHA-256 reproduced the pin exactly (fresh re-pull). The fresh re-pull was executed 2026-10-28T16:01Z and reproduced `c62b878cb915410f2c364a590bd1b3e01f15fea26acc79e2e6f4c8e242bcd7f7368` on 549,267,055 bytes.

**No season is missing upstream.** All nine seasons the CBB screens use
(2015–2023) exist in the release; no season is flagged NOT PINNABLE, and
no substitute source was used for any season. (The release also carries
seasons 2003 and 2006–2014 and 2024+; they are outside the screens'
window and are not pinned.)

## 4. Schema verification — the fields a 1H derivation consumes

A first-half team-points derivation needs exactly five things from the
rows: which game, which half, the game clock, which team scored, and
how many points. All five are present, under stable names, in **every**
pinned season (verified-by-pull, per-season header audit):

| Role | Field(s) | Notes |
|---|---|---|
| Game identity | `game_id` | ESPN event ID — the same ID space as the admitted schedules' `id` |
| Period / half | `period_number` | 1 = first half, 2 = second half, ≥3 = overtime periods (observed range 1–6); `period_display_value` carries the display form ("1st Half") |
| Game clock | `clock_display_value` (with `clock_minutes`, `clock_seconds`) | time remaining in the period |
| Scoring team | `team_id`, attributed against `home_team_id` / `away_team_id` carried on every row | |
| Points value | `score_value` on rows flagged `scoring_play` | `scoring_play` takes the string values `true` / `false` in every pinned season |
| Running score | `away_score`, `home_score` | cumulative score after each play — an independent second derivation path |

Two derivations of first-half team points are therefore possible from
the pinned bytes alone, and §5–§6 use both:

- **Method A (running score):** a team's halftime points are its
  running score at the end of period 1 (the maximum of its running
  score over period-1 rows; the running score is cumulative).
- **Method B (scoring plays):** a team's halftime points are the sum of
  `score_value` over period-1 rows with `scoring_play` = true and
  `team_id` equal to that team's ID. **Method B was executed as a
  cross-check and FAILED (§6): the feed's `scoring_play` flag is
  unreliable. Method B is refused as a derivation; Method A is the
  admitted derivation.**

**Schema-era differences (verified-by-pull).** The column **set** is identical to 2015's for 2016–2020. Three era differences exist, all outside the core fields: (i) 2021–2023 drop the `media_id` column and add a `wallclock` column; (ii) 2023 additionally drops the derived helper columns `qtr`, `period`, `half`-era `game_half`, `lag_qtr`, `lead_qtr`, `lag_game_half`, `lead_game_half`, `start_quarter_seconds_remaining`, `start_half_seconds_remaining`, `end_quarter_seconds_remaining`, `end_half_seconds_remaining` and adds `away_timeout_called`, `home_timeout_called`, `lag_half`, `lag_period`, `lead_half`, `lead_period`, `start_period_seconds_remaining`, `end_period_seconds_remaining` (period-named successors of the same derived family); (iii) column **order** differs between seasons (e.g. 2015 vs 2017+) even where the set is identical — consumers must read by field name, never by position. The core fields
above are untouched by these differences: every pinned season carries
all of them under the same names and the same value conventions, so one
derivation consumes all nine seasons without per-era field mapping.

## 5. Coverage and integrity (verified-by-pull, full-join)

| Season | PBP rows | Schedule games | PBP games | Schedule games with no PBP | Method-A finals agreeing with schedule |
|---|---|---|---|---|---|
| 2015 | 1,737,302 | 5,932 | 5,280 | 11.0% | 5,185 / 5,280 (98.20%) |
| 2016 | 1,803,531 | 5,893 | 5,390 | 8.5% | 5,300 / 5,390 (98.33%) |
| 2017 | 1,818,853 | 5,960 | 5,479 | 8.1% | 5,400 / 5,479 (98.56%) |
| 2018 | 1,827,395 | 6,003 | 5,645 | 6.0% | 5,576 / 5,645 (98.78%) |
| 2019 | 1,787,332 | 6,049 | 5,474 | 9.5% | 5,386 / 5,474 (98.39%) |
| 2020 | 1,746,980 | 5,767 | 5,394 | 6.5% | 5,293 / 5,394 (98.13%) |
| 2021 | 1,296,252 | 4,285 | 4,015 | 6.3% | 3,957 / 4,015 (98.56%) |
| 2022 | 1,860,561 | 5,976 | 5,830 | 2.4% | 5,765 / 5,830 (98.89%) |
| 2023 | 1,957,375 | 6,261 | 6,116 | 2.3% | 6,041 / 6,116 (98.77%) |

Totals: 52,126 schedule games, 48,623 PBP games, 48,623 joined (PBP is a strict subset of the schedule universe on ESPN game IDs — 0 PBP games fall outside it, in every season).

Readings: coverage is thinnest in the earliest seasons (2015: 11.0% of schedule games have no PBP) and tightest in the latest (2023: 2.3%); a fixture with no PBP is NO_DATA for 1H purposes and is excluded by the screen's fixture discipline, never imputed. Method-A finals reproduce the admitted schedule finals on 98.13–98.89% of joined games per season. The residual 1.1–1.9% is a PBP-defect class, adjudicated in §6.

## 6. Sample checks — 1H points derived and cross-checked

Sample design (chosen deterministically from the admitted schedules before any PBP content was read): per season, the earliest game, the latest game (the championship game in tournament seasons), and the games at the one-third and two-thirds positions of the date-sorted schedule — 36 games across the nine seasons.

- **33 of the 36** sample games are present in the pinned PBP. The three absent games — 400809216 (2016 opener), 401082362 (2019 opener), 401269640 (2021) — are part of the §5 coverage gap and are named, not smoothed over.
- For all **33 present games, Method A halftime points agree exactly with ESPN's published first-half linescores — 33/33**, including all nine seasons' championship games (e.g. 2015: derived 31–31 at the half, final 63–68; 2023: derived 24–36, final 59–76 — both matching the published record).
- **Method B agrees on only 30/33** sample games and far worse across the full join (its finals match the schedule on just 79.95–97.05% of games per season, degrading in later seasons). Diagnosis (verified-by-pull on named games): the feed's `scoring_play` flag is unreliable — made baskets occur with `scoring_play` = false (e.g. game 401369943, 2022: unflagged made JumpShots, score increments landing on End Period and Personal Foul rows), and isolated early-era feeds contain duplicated segments with distinct play IDs that inflate any sum (e.g. game 400589378, 2015: 695 rows, the running score resetting six times; the sum reads 167–219 against a true 80–93, while Method A reads 80–93 exactly). **Method B is therefore REFUSED as a derivation** (see §4 and the manifest's schema verification): first-half points are derived by Method A only, and any consumer summing `score_value` over flagged rows is out of compliance with this admission.
- **Final-disagreement adjudication:** for one Method-A final-disagreement game per season (9 games), ESPN's published final (summary document) was compared against both artifacts. It sided with the **admitted schedule in 9/9** cases (worst case: a 2018 game whose PBP feed reads 44–55 against a true 53–73 — a severely truncated feed). The disagreement class is PBP-feed defects, and it is removable by construction: any missing or extra scoring event anywhere in a game breaks the derived final's equality with the schedule final. **The gate is therefore binding on consumers: a fixture's first-half points may be consumed only when its Method-A derived final equals the admitted schedule final for that game.** Ungated halftime consumption is out of compliance with this admission. On the gated universe the derivation is the one proven 33/33 above; sanity holds structurally as well — across all 48,623 PBP games there are zero games with a nonzero final but a zero halftime, and zero games whose halftime exceeds their final.

**Check sources, stated honestly.** Finals are checked against the
admitted schedule substrate on the full join (§5) — every game, not a
sample. Halftime scores have no second-provenance source available to
this program: the College Basketball Reference game logs admitted by
PR #2871 carry final scores only (verified-by-pull: their columns are
`TeamScore` / `OpponentScore` with no half split), so they cannot check
halves. The halftime check therefore uses ESPN's own published
linescores for the same games (the summary document behind ESPN's
gamecast pages — a different artifact and endpoint from the PBP feed,
and the same provider). Agreement there proves the PBP derivation is
faithful to ESPN's published half scores; it is **not** an
independent-provenance verification of the halves, and none is claimed.
The design (CBB_TEAM_TOTALS_1H_DESIGN §2) requires the half share to be
fitted from, and 1H outcomes derived from, the pinned PBP itself; it
assumes no external half-split source.

## 7. What this admission satisfies — and its scope lock

- The named prerequisite of `CBB_TEAM_TOTALS_1H_DESIGN.md` §2 — hoopR
  play-by-play release assets pinned full-tuple **with schema
  verification** — is **SATISFIED BY THIS MANIFEST** (on merge, after
  independent review). The `PBP_PREREQUISITE_MISSING` recorded by
  PR #2892 is cleared **for design-screen use of the CBB first-half
  family only**.
- **Scope lock (binding):** the pinned PBP may be used to (a) fit the
  first-half share on seasons strictly before each scored season and
  (b) derive 1H outcomes (first-half team points), under the 1H design's
  screen shape (1H-total MAE and 1H-margin MAE vs a naive half-share
  climatology baseline, DESIGN-evidence label at most). No other use is
  admitted: no full-game modeling input, no player-level use, no other
  family's substrate.
- The pinned seasons are **design data** — they are the same historical
  span the CBB screens already use — and can never later be presented
  as untouched validation. Verification accrues **forward only**, from
  admitted pregame captures, under the family's own forward terms.
- **State-transition note (disclosed for the reviewer):** the
  team-totals runner's prerequisite scan
  (`run_team_totals_screen.py::find_pbp_manifest`) was built for this
  landing — with this manifest present it reports
  `PREREQUISITE_PRESENT — NOT RUN BY THIS PACKET` instead of the
  refusal. The one guard test that asserted the pre-admission state
  (`tests/test_cbb_team_totals.py::test_first_half_prerequisite_absent_on_main`)
  is updated **in this same PR** to assert the post-admission state
  exactly (the scan finds exactly this manifest, nothing else) — same
  strictness, new state. The committed #2892 `screen_result.json` is
  untouched: its first-half block remains NOT_EXECUTABLE, as executed
  at its run time; this admission changes what a *future* 1H screen
  act may rely on, not what the executed run recorded.

## 8. Refusals

`SOURCE_UNAVAILABLE`, `ASSET_MISSING` (tag/asset not found),
`SIZE_MISMATCH`, `SOURCE_CHANGED_AFTER_SNAPSHOT` (hash drift vs this
manifest), `SCHEMA_INVALID` (any pinned asset missing a §4 core field,
or `scoring_play` value conventions changed), `IDENTITY_UNVERIFIED`
(any join beyond the ESPN game-ID space shared with the admitted
schedules), `ILLINOIS_COLLEGE_BLOCKED`,
`CBR_HALF_SPLIT_NOT_AVAILABLE` (any attempt to cite the College
Basketball Reference logs as a half-score source — they carry finals
only).

## 9. What this admission does NOT do

- It does **not** run the CBB first-half design screen, fit the
  first-half share, or produce any screen verdict. The screen is a
  separate act under `CBB_TEAM_TOTALS_1H_DESIGN.md` §2, run on these
  pins.
- It does **not** supply a market baseline: no historical 1H lines are
  in this source, and none are claimed; the design's forward market leg
  still rests on DraftKings captures under the family's forward terms.
- No CBB engine, freeze, or forward clock is created; no threshold
  changes. This record admits no identity crosswalk and relies on none: the PBP joins to
  the admitted schedules on ESPN game IDs inside one provider's ID
  space, which is an ID match, not a crosswalk; name-only joins remain
  refused. Illinois-college fixtures remain excluded under the same
  rules as the parent design; KenPom data enters nowhere: **KenPom is
  NOT ADMITTED** (paid; owner ruling), and no `kp_*` identifier may be
  used to fetch or join KenPom data products.

## 10. Owner / reviewer decisions still required

1. Accept this DESIGN-only PBP admission (merge of this PR after Rocky
   review) — this is what clears `PBP_PREREQUISITE_MISSING` for the 1H
   design screen.
2. Separately: the CBB first-half design screen itself, run under the
   design's §2 shape on these pins (a later act; not this record).
3. Separately (unchanged from PR #2835/#2867): the crosswalk admission
   and the forward data gates of the parent CBB families.
