# Admission record — hoopR MBB historical schedules successor manifest (seasons 2015–2023) + College Basketball Reference leg attempt

**Status: SAMPLE-VERIFIED / ADMISSION PROPOSED — DESIGN ONLY — NOT VALIDATION —
NO FORWARD-CLOCK CREDIT — NO PLAY ELIGIBILITY.**
Prepared 2026-10-28 (hoopR pull 2026-10-28T10:42:46Z; College Basketball
Reference attempt 2026-10-28T10:43:44Z) for independent review. Admission
takes effect only if this PR is merged after independent (Rocky) review,
and even then the substrate is a **design / baseline input only**.

**Purpose — the unblock this record exists for.** The
CBB_TORVIK_EFFICIENCY_V1 design screen (PR #2843,
`research/nba_cbb_activation_20261028/CBB_SIDES_TOTALS_DESIGN_AND_PREREG_DRAFT.md`
§3) requires three data pins **before any run**. PR #2866 executed the
precondition check and recorded the screen **NOT_EXECUTABLE**: precondition
(a), the Torvik archive at the PR #2832 pinned commit, is MET; precondition
(b), the historical schedule/results full-tuple pin under a successor
manifest to PR #2835, was NOT MET — #2835 pinned only the 2027 schedule,
the 2026 player box, and the 2026 crosswalks. **This record is that
successor manifest.** It does not run the screen; it supplies the missing
pin so the screen may then run exactly as designed.

Every factual claim carries an evidence state: **verified-by-pull**
(checked against bytes or API responses fetched from the SportsEdge
runtime) or **documented-only** (provider documentation / design text;
not reproduced here).

## 1. Source and provenance

- **What is pinned:** ESPN-derived NCAA Division I men's basketball
  schedules/results for the seasons ending 2015–2023 (i.e. 2014-15 →
  2022-23, exactly the design screen's stated coverage), assembled by
  the **sportsdataverse** project and consumed by hoopR's
  `load_mbb_schedule`. Canonical route (verified-by-pull): GitHub
  release assets of `sportsdataverse/sportsdataverse-data`, release
  `espn_mens_college_basketball_schedules` (release ID 97399224 — the
  same release PR #2835 sampled), assets `mbb_schedule_<season>.csv` and
  `mbb_schedule_<season>.parquet` for each season 2015–2023.
- **Licenses (verified-by-pull, per PR #2835):** `sportsdataverse-data`
  — MIT; ESPN's own terms govern the underlying data. This repo commits
  **hashes, manifests and retrieval code only — no data files**.
- **The third leg:** Sports Reference's College Basketball Reference
  (`sports-reference.com/cbb`) season schedules, named by the design
  (PR #2843 §2) as the independent cross-check in the three-way fixture
  agreement. Attempted here; **refused upstream** — see §5.

## 2. The pin rule — rolling release, attestation at pull timestamp

PR #2835's central finding stands and governs here: the schedules
release is **rolling** — assets are replaced in place under a stable
tag, so **a tag pins nothing**. The pin for every asset in this manifest
is the full tuple:

> **release tag + release ID + asset ID + asset size + asset
> `updated_at` + SHA-256 of the downloaded bytes**, recorded in
> `successor_manifest.json` together with the pull timestamp
> (`retrieved_at_utc` = 2026-10-28T10:42:46Z).

**Attestation scope, stated plainly:** because the release is rolling,
this pin attests the bytes **as pulled at that timestamp** — the
strongest attestation this source supports. It does **not** attest that
upstream bytes are stable or immutable, and no such claim is made. The
historical-season assets carried `updated_at` values in 2023 at pull
time; that is an observation about the pull, not a stability guarantee.
The committed script `pull_hoopr_mbb_schedules.py` re-downloads every
pinned asset and compares size + SHA-256; any drift is
`SOURCE_CHANGED_AFTER_SNAPSHOT` — a **refusal**, never silent
acceptance — and a drifted asset may only re-enter through a successor
manifest with its own review. Formats are pinned independently; one
format's pin never vouches for another. (The `.rds` twin of each season
exists upstream and is deliberately not pinned: it is not a consumed
route in this repo — the same treatment PR #2835 applied, which pinned
no `.rds` asset.)

## 3. Hash-verified samples (pulled 2026-10-28T10:42:46Z)

All 18 assets are in release `espn_mens_college_basketball_schedules`
(release ID 97399224). Every downloaded byte count matched the GitHub
API's reported asset size exactly at pull time (verified-by-pull).

| Asset | Asset ID | `updated_at` | Bytes | SHA-256 |
|---|---|---|---|---|
| `mbb_schedule_2015.csv` | 103081996 | 2023-04-10T21:20:31Z | 4,396,911 | `6ae65bd03ea48c147815bcd8806597787ad6a098cbe1be1da5425c3d8901edd8` |
| `mbb_schedule_2015.parquet` | 103082002 | 2023-04-10T21:20:32Z | 618,686 | `3c7aa3002e0417aa74d15533cd7a1dbdcf4f599297c3997116cdb30f07905cab` |
| `mbb_schedule_2016.csv` | 103082656 | 2023-04-10T21:26:44Z | 4,370,181 | `dab89af97fc3db78e53487f35bdd6eb145fe04fe50e994bb28f15198050b2e46` |
| `mbb_schedule_2016.parquet` | 103082660 | 2023-04-10T21:26:45Z | 617,730 | `9b401f9905bd97e032b99ba5899cd65ff3b4e6b44edab1f36618908a3b0152ff` |
| `mbb_schedule_2017.csv` | 103104001 | 2023-04-11T01:13:33Z | 4,403,551 | `350c92cd159f547e6956fd7390530df2daee63b0f2eaccc41b39085d4ad5e7e6` |
| `mbb_schedule_2017.parquet` | 103104006 | 2023-04-11T01:13:34Z | 593,064 | `ce90db03f344f6a12c44155f2f70534a7df9e9f56f5c5bb38e6c292149388802` |
| `mbb_schedule_2018.csv` | 103093328 | 2023-04-10T23:17:32Z | 4,457,335 | `6732b013871de9979b59b92084190adc849c131dc265d6fbd7ff295a7b7fdfc1` |
| `mbb_schedule_2018.parquet` | 103093330 | 2023-04-10T23:17:34Z | 623,847 | `2ec927051e55807a7d02d5f176576cf7a29a5ee2b7471817e2ced43a38aa0aa5` |
| `mbb_schedule_2019.csv` | 103094377 | 2023-04-10T23:35:36Z | 4,492,283 | `745d214e1bd6d1352bab71506aa56e9fd47392b049f23fb3a79e89e51759ce79` |
| `mbb_schedule_2019.parquet` | 103094378 | 2023-04-10T23:35:37Z | 627,071 | `c285df779882719857048b1478c15d21868f4fdbe7d7d75d2ecb4f4ab970fb71` |
| `mbb_schedule_2020.csv` | 103093091 | 2023-04-10T23:13:51Z | 4,271,530 | `2e41af0af1ed0f5347f2a259ec9ed635d5d9a3b30daad4b69b924591f87319e0` |
| `mbb_schedule_2020.parquet` | 103093093 | 2023-04-10T23:13:52Z | 598,411 | `f87d7a04d905c95221b1201a4fd43bdf9bad3bfae7b3f880800e9eb8ae1cfa3a` |
| `mbb_schedule_2021.csv` | 103093435 | 2023-04-10T23:18:57Z | 3,185,330 | `37dfdddcbe2ef3ac43926e4b35f01672703e09a3da3efcc7944634fcf1fec3ec` |
| `mbb_schedule_2021.parquet` | 103093437 | 2023-04-10T23:18:59Z | 465,503 | `26b26e9fd035a567ca66e65fadd8a3df9482e25e4a1c63ff40466e0d99c9cc76` |
| `mbb_schedule_2022.csv` | 103094601 | 2023-04-10T23:39:10Z | 4,426,306 | `70a341f448e197e0443ab6a8bd4a168c0a419db78d91abb842f4e6802cf2db7d` |
| `mbb_schedule_2022.parquet` | 103094603 | 2023-04-10T23:39:11Z | 621,024 | `75a702d5c8db85bfd7ad30bc046a801742b88ac3f7a900d7e05450a6a4c10276` |
| `mbb_schedule_2023.csv` | 136828032 | 2023-11-22T03:45:55Z | 9,150,417 | `41991919d7b39032be40c4b259aedbad8f404f9993fc6139361d0af69b9a89a2` |
| `mbb_schedule_2023.parquet` | 136828039 | 2023-11-22T03:45:58Z | 1,039,184 | `1a75500bd669a2e0f01b39623a1aa28d8d4cc1b8658f8adbabfc5319c73c496c` |

**No season is missing upstream.** All nine seasons the design names
(2015–2023) exist in the release in both pinned formats; no season is
flagged NOT PINNABLE, and no substitute source was used for any season.

## 4. Content sanity evidence (verified-by-pull, CSV assets)

Row counts use the same coverage discipline as PR #2835's Nov-1 check:
counts and date ranges must sit in the sane band for a Division I season
before the pin is believed.

| Season | Rows | `game_date` range | Both final scores populated | `status_type_completed` |
|---|---|---|---|---|
| 2015 (2014-15) | 5,932 | 2014-11-14 → 2015-04-06 | 5,932 / 5,932 | 5,932 |
| 2016 (2015-16) | 5,893 | 2015-11-13 → 2016-04-04 | 5,893 / 5,893 | 5,893 |
| 2017 (2016-17) | 5,960 | 2016-11-11 → 2017-04-03 | 5,960 / 5,960 | 5,960 |
| 2018 (2017-18) | 6,003 | 2017-11-10 → 2018-04-02 | 6,003 / 6,003 | 6,003 |
| 2019 (2018-19) | 6,049 | 2018-11-06 → 2019-04-08 | 6,049 / 6,049 | 6,049 |
| 2020 (2019-20) | 5,767 | 2019-11-05 → 2020-03-11 | 5,767 / 5,767 | 5,767 |
| 2021 (2020-21) | 4,285 | 2020-11-25 → 2021-04-05 | 4,285 / 4,285 | 4,285 |
| 2022 (2021-22) | 5,976 | 2021-11-09 → 2022-04-04 | 5,976 / 5,976 | 5,976 |
| 2023 (2022-23) | 6,261 | 2022-11-07 → 2023-04-03 | 6,261 / 6,261 | 6,228 |

Readings, all consistent with the historical record: every season opens
in November and closes with the early-April championship window; the
2020 season ends 2020-03-11 and the 2021 season is short (4,285 rows,
late start 2020-11-25) — the COVID-19 cancellation and shortened
season, i.e. the true record, not missing data. The 2023 CSV carries
extra columns (broadcast, current-rank, linescores, records) and is ~2×
the bytes of earlier seasons — schema differs by season and consumers
must not assume one schema. In 2023, 33 rows carry both final scores
without the `status_type_completed` flag; adjudicating such rows is the
design screen's fixture-agreement step, not this admission's. ESPN
identifiers are present throughout (game `id`, `home_id`, `away_id`,
`neutral_site`, `home_score`, `away_score`) — the fields the design's
three-way agreement and venue flag consume.

**Parquet caveat:** the SportsEdge runtime has no working parquet
reader at admission time, so the nine `.parquet` assets are admitted on
bytes + hash, with row content cross-verified through each season's CSV
twin (whose bytes differ by format) — exactly the treatment PR #2835
applied to its parquet samples.

## 5. College Basketball Reference leg — REFUSED, not pinned

The design (PR #2843 §2) names College Basketball Reference's season
schedule as the third leg of the fixture agreement. For this record the
season schedule pages were pulled for the nine design seasons
(`https://www.sports-reference.com/cbb/seasons/men/<ending-year>-schedule.html`,
ending years 2015–2023), serially, with an honest User-Agent and ≥5s
spacing, at 2026-10-28T10:43:44Z. **The first request (2015) returned
HTTP 403.** Sports Reference's bot policy is honored fail-closed in this
program (403/429 = stop; cf. the current-form analytics wiring, PR
#2845), so the remaining eight seasons were **not attempted**, and no
circumvention of any kind was tried. The full attempt record is in
`successor_manifest.json` under `cbr_leg`
(status `REFUSED_HTTP_403_NOT_PINNED`).

**What remains unpinned, stated plainly:** the entire College
Basketball Reference leg — all nine season-schedule pages. It remains
**documented-only**, exactly as the design recorded it. Consequences:

- This manifest satisfies precondition **(b)** only (see §6). It does
  not complete precondition **(c)**: no three-way fixture agreement may
  be asserted from this manifest, because the CBR leg has no pin.
- The CBR leg can only enter through a later, separate record once a
  lawful pull succeeds (e.g. an egress Sports Reference does not
  refuse) — pulled and hash-pinned the same way, with its own review.

## 6. Precondition accounting (design PR #2843 §3; screen record PR #2866)

- **(a) Torvik archive files via the #2832 retrieval script at its
  pinned commit — MET** (per PR #2866; untouched by this record). The
  morning-of as-of rule of that admission binds the screen's use: the
  archive file for date D is the rating as of the morning of D.
- **(b) Historical schedule/results assets pinned by the full-tuple
  rule of PR #2835 under a successor manifest — SATISFIED BY THIS
  MANIFEST** (on merge, after independent review). With (a) already met
  and (b) supplied here, the design screen's **data-pin preconditions
  for the schedule leg are complete**, and the screen may then run
  exactly as designed in PR #2843 §3 — walk-forward by season, design
  evidence only, DESIGN_PASS at most.
- **(c) Three-way fixture agreement — PARTIALLY OUTSTANDING.** The
  hoopR leg is pinned here and the Torvik leg under (a); the College
  Basketball Reference leg is refused/unpinned (§5). The design's own
  text governs what the screen may claim: a fixture enters the screen
  only on three-way agreement, so fixtures cannot be three-way-verified
  until the CBR leg is pinned by a successor record. That is a
  disclosed gap carried forward — not waived, not papered over, and
  not silently downgraded by this admission.

## 7. Identity crosswalk and Illinois exclusion — unchanged

This manifest pins schedule bytes only. The ESPN ↔ Torvik ↔ NCAA
identity crosswalk remains **OPEN — not admitted** (PR #2835 §4):
provider crosswalk matches are confidence-scored, no NCAA game-ID
column was observed, and name-only joins are refused outside the design
screen's own audited, design-evidence-only expedient (PR #2843 §2).
Nothing in this record admits an identity mapping.

CBB modeling scope **excludes Illinois college teams** (college only;
Illinois professional teams in other sports are in scope). The design
screen's conservative name/conference over-exclusion (PR #2843 §2)
remains the only design-stage expedient; the production ID-based,
fail-closed exclusion still depends on the crosswalk admission. KenPom
data enters nowhere, in any leg: **KenPom is NOT ADMITTED** (paid;
owner ruling), and no `kp_*` identifier may be used to fetch or join
KenPom data products.

## 8. Refusals

`SOURCE_UNAVAILABLE`, `ASSET_MISSING` (tag/asset not found),
`SIZE_MISMATCH`, `SOURCE_CHANGED_AFTER_SNAPSHOT` (hash drift vs this
manifest), `SCHEMA_INVALID`, `IDENTITY_UNVERIFIED` (any join without an
admitted crosswalk), `ILLINOIS_COLLEGE_BLOCKED`,
`CBR_LEG_NOT_PINNED` (any attempt to claim a three-way fixture agreement
including College Basketball Reference on the basis of this manifest).

## 9. What this admission does NOT do

- It does **not** run the CBB_TORVIK_EFFICIENCY_V1 design screen, fit
  any parameter, or produce any screen verdict. The screen is a separate
  act under PR #2843 §3, run on these pins.
- No CBB engine, freeze, or forward clock is created; no threshold
  changes. The pinned seasons are **design data** — several were visible
  to earlier CBB exploration — and can never later be presented as
  untouched validation. The forward prereg's data gates (PR #2843 §5)
  are entirely unaffected: the live-season Torvik route blocker and the
  crosswalk admission remain exactly as recorded there.
- Verification accrues **forward only**, from admitted pregame
  captures, under a family's own preregistration. PAPER / research
  only: 0u, no staking, no wager execution.

## 10. Owner / reviewer decisions still required

1. Accept this DESIGN-only successor admission (merge of this PR after
   Rocky review) — this is what satisfies design precondition (b).
2. Separately, when a lawful route exists: a College Basketball
   Reference pin record completing precondition (c)'s third leg.
3. Separately (unchanged from PR #2835): the crosswalk admission, and a
   live-season (2026-27) Torvik morning-of route — both forward-prereg
   gates, not screen gates.
