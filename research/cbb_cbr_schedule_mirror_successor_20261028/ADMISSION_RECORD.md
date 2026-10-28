# Admission record — College Basketball Reference schedule mirror successor manifest (CBR third leg, seasons 2014-15 → 2022-23)

**Status: SAMPLE-VERIFIED / ADMISSION PROPOSED — DESIGN ONLY — NOT VALIDATION —
NO FORWARD-CLOCK CREDIT — NO PLAY ELIGIBILITY.**
Prepared 2026-10-28 (mirror pull 2026-10-28T11:27:11Z) for independent
review. Admission takes effect only if this PR is merged after
independent (Rocky) review, and even then the source is a **design /
cross-check input only** — the role the design itself assigns it
(PR #2843 §2: "cross-check / reference only"; not a ratings input, not
a validation or market baseline, not an identity admission).

**Purpose — the unblock this record exists for.** The
CBB_TORVIK_EFFICIENCY_V1 design screen (PR #2843,
`research/nba_cbb_activation_20261028/CBB_SIDES_TOTALS_DESIGN_AND_PREREG_DRAFT.md`
§3) requires three data pins **before any run**. PR #2866 recorded the
screen **NOT_EXECUTABLE** on precondition (b); PR #2867 supplied (b)
and recorded precondition (c) — the §2 three-way fixture agreement —
as outstanding because its College Basketball Reference leg was
**refused upstream (HTTP 403)** and unpinned. PR #2870 re-ran the
precondition check and recorded **NOT_EXECUTABLE** again, on (c)
alone, adjudicating from the design text that the §2 "enters only on
three-way agreement" gate is a required data input, not waived by the
cross-check role limits. **This record is the successor manifest
PR #2867 §5 anticipated** ("the CBR leg can only enter through a
later, separate record once a lawful pull succeeds"): it pins the
CBR season schedules from a lawful, provenance-documented public
mirror. It does not run the screen; it supplies the missing pin so
the screen may then run exactly as designed.

Every factual claim carries an evidence state: **verified-by-pull**
(checked against bytes or API responses fetched from the SportsEdge
runtime) or **documented-only** (provider documentation / design text;
not reproduced here).

## 1. Source and provenance chain

- **What is pinned:** College Basketball Reference (CBR) NCAA
  Division I men's basketball team game logs — date, opponent, and
  final scores per game — for the seasons 2014-15 → 2022-23, exactly
  the design screen's stated coverage and exactly the third leg the
  design §2 names ("College Basketball Reference's season schedule —
  same fixture, same date, same final score").
- **Provenance chain (verified-by-pull from the repo itself):**
  **CBR → scraper → committed mirror.**
  1. *Origin:* CBR's team game-log tables at
     sports-reference.com/cbb. No request to sports-reference.com was
     made for this admission — the only CBR pull on record remains
     PR #2867's fail-closed HTTP 403, and Sports Reference bot policy
     (403/429 = stop, no circumvention) is honored throughout.
  2. *Scraper:* the mirror repo's own `sports-data-catalog.html`
     documents `LogScraperScript.R` as *"the CBB team game log
     scraper"* with source **sports-reference.com/cbb** and method
     "HTML table scraping", producing the season log files. The
     repo's published analyses consuming these exact files describe
     the SRS/SOS system the logs carry as Sports Reference's.
  3. *Mirror:* the files are committed in the public GitHub repo
     **`mattwaite/mattwaite.github.io`** under `sportsdatafiles/` —
     a university professor's long-standing public teaching dataset
     (per-file last-touch commits run 2020-12-28 → 2024-04-10).
  In-data provenance corroborates the chain: every per-season row
  carries CBR's own school-page URL
  (`/cbb/schools/<slug>/men/<year>.html`) and CBR's signature
  SRS/SOS columns, and the column layout is CBR's team game-log
  table.
- **One catalog inaccuracy, recorded honestly** (from the source
  hunt): the catalog advertises individual `logs15.csv`–`logs24.csv`
  files; the repo actually commits individual files only for
  2019–2026 plus the merged `logs1520.csv` for the earlier seasons.
  The pin in §3 describes what is actually committed, not what the
  catalog advertises.
- **This repo commits hashes, manifests and retrieval code only —
  no data files.**

## 2. Authorization posture — stated plainly, not papered over

The mirror asserts **no license** (no LICENSE file in the repo) and
**no Sports Reference authorization**, and this record claims
neither. The posture under which these bytes are consumed here:

- What is consumed is **factual game data — dates, opponents, final
  scores** (facts, not creative expression).
- Consumption is **read-only** and **internal verification only**
  (the §2 fixture-agreement cross-check inside a design screen).
- The bytes are **hash-pinned and never redistributed**: this repo
  stores the manifest, the hashes and the derivation code; the data
  files live outside the repo in the admission workspace.
- The alternative the program already tried — pulling CBR directly —
  is refused upstream under bot policy, and no circumvention of that
  refusal was attempted or is proposed. If the owner rejects this
  mirror posture, the ranked fallback amendments are documented in
  the source-hunt report (Kaggle March Madness mirror — independent
  but not CBR; NCAA official — authoritative but no bulk route;
  KenPom — rejected, paid; any ESPN route — rejected, fails the
  independence the third leg exists for).

## 3. The pin rule — commit-anchored full tuple

The pin for every file in this manifest is the full tuple:

> **repo + commit SHA + path + git blob SHA + asset size + SHA-256
> of the pulled bytes**, recorded in `successor_manifest.json`
> together with the pull timestamp (`retrieved_at_utc` =
> 2026-10-28T11:27:11Z).

This pin is **commit-anchored** — stronger than PR #2867's rolling
release attestation: the pull URLs are addressed by the full commit
SHA (`48e22e1c5f39b47425aa64f8fc98112974b5a8c0`), so upstream bytes
cannot drift under the pin without the commit itself changing. The
committed script `pull_cbr_schedule_mirror.py` re-downloads every
pinned file at that commit and compares size + SHA-256 + git blob
SHA (the blob SHA is recomputable from the bytes alone); any drift
is `SOURCE_CHANGED_AFTER_SNAPSHOT` — a **refusal**, never silent
acceptance — and a drifted file may only re-enter through a
successor manifest with its own review.

**Re-verification against the source hunt (verified-by-pull):** the
hunt located this source and recorded sha256 / blob SHA / size for
all six files from its own pulls. This admission re-pulled every
file independently at the pinned commit: **6/6 reproduce the hunt
report's values exactly** (sha256, git blob SHA and size all match,
per file, §4). No value in §4 is copied from the hunt unverified.

## 4. Hash-verified samples (pulled 2026-10-28T11:27:11Z)

All six files are in `mattwaite/mattwaite.github.io` at commit
`48e22e1c5f39b47425aa64f8fc98112974b5a8c0`, paths under
`sportsdatafiles/`.

| File | Git blob SHA | Bytes | SHA-256 | Admitted seasons |
|---|---|---:|---|---|
| `logs1520.csv` | `97bffa2570c18163488bde0306acfa737210befe` | 12,681,623 | `17d2e61d32880005238c55bdd6dfcf3807950195844f25bb094d2872d302b3f9` | 2014-15 → 2017-18 ONLY |
| `logs19.csv` | `ba46cdd5c3c38ca793f8413dc6d6f387128af8ca` | 2,914,156 | `d5035f37789d4a0b556cdb6824efa344db296ebc0e1248936ebf5cc5010ca4ff` | 2018-19 |
| `logs20.csv` | `66bf0d6bf2dfdf71117a793d52bcb8f2649e7a84` | 2,770,086 | `42ae4ab716aff6e04279c4b6f9ba9fba6fc681fa65694f6c8b1ce7868bfba4ff` | 2019-20 |
| `logs21.csv` | `38adba0fa6980b03c46600d8a88d844357a0e691` | 2,031,033 | `5cf27d1db16aa35d5ab42e268ebe3c6ec3610ae8970fa42e7d096c24724321d0` | 2020-21 |
| `logs22.csv` | `200094f671d73a4d393803cd2fd6147018ecdc66` | 2,854,222 | `1117fe9f97989e9c7012edc9083bdfa1746f94f63f29437e1c095768010c8108` | 2021-22 |
| `logs23.csv` | `a3e25cecb6726b5c9422f7b35ccef808eb2cb682` | 3,008,747 | `eb1d2cac051d21b52068441313ddc6506135c6086e57079b95132f2b7f141aa6` | 2022-23 |

**No season is missing.** All nine seasons the design names
(2014-15 → 2022-23) are pinned; no season is flagged NOT PINNABLE,
and no substitute source was used for any season.

## 5. Admitted season scopes — and what is NOT admitted

- **`logs1520.csv` is admitted for 2014-15 → 2017-18 ONLY**
  (11,431 / 11,468 / 11,511 / 11,544 team-rows). The same file also
  carries 2018-19 rows (11,566) and 2019-20 rows (11,097); **both
  are excluded from the pin**: its 2018-19 rows stop at 2019-03-24
  (the late tournament is missing), and its 2019-20 rows duplicate
  the `logs20.csv` season without being identical to it (11,097 vs
  11,095 rows). The 2018-19 season is admitted from `logs19.csv`
  and 2019-20 from `logs20.csv`. Any consumer reading `logs1520.csv`
  outside its admitted seasons is off-pin.
- **The merged files are NOT admitted (documented rejection):**
  `cbblogs1521.csv` / `cbblogs1522.csv` in the same repo are
  inconsistent composites — their 2014-15 → 2017-18 portions hold
  only ~9,058–9,168 team-rows per season (vs ~11.4–11.5k in
  `logs1520.csv`) and `cbblogs1522`'s 2021-22 portion ends
  2022-03-06, before the conference tournaments. They remain useful
  only as a cross-check of the merges' existence, never as admitted
  bytes.
- Direct sports-reference.com schedule pages remain
  `REFUSED_HTTP_403_NOT_PINNED` (PR #2867) — superseded as a route
  by this mirror pin, not retried.

## 6. Content sanity evidence (verified-by-pull)

Row counts are **team-rows** (one row per team per game), the unit
of the source — not fixtures. Fixture derivation is §7.

| Season | Source file | Team-rows | Date range |
|---|---|---:|---|
| 2014-15 | `logs1520.csv` | 11,431 | 2014-11-14 → 2015-04-06 |
| 2015-16 | `logs1520.csv` | 11,468 | 2015-11-13 → 2016-04-04 |
| 2016-17 | `logs1520.csv` | 11,511 | 2016-11-11 → 2017-04-03 |
| 2017-18 | `logs1520.csv` | 11,544 | 2017-11-10 → 2018-04-02 |
| 2018-19 | `logs19.csv` | 11,652 | 2018-11-06 → 2019-04-08 |
| 2019-20 | `logs20.csv` | 11,095 | 2019-11-05 → 2020-03-11 |
| 2020-21 | `logs21.csv` | 8,229 | 2020-11-25 → 2021-04-05 |
| 2021-22 | `logs22.csv` | 11,443 | 2021-11-09 → 2022-04-04 |
| 2022-23 | `logs23.csv` | 11,995 | 2022-11-07 → 2023-04-03 |

Readings, all consistent with the historical record: every season
opens in November and closes in the early-April championship window;
the 2020 season ends 2020-03-11 and the 2021 season is short (8,229
rows, late start 2020-11-25) — the COVID-19 cancellation and
shortened season, i.e. the true record, not missing data. Schemas
differ between the merged-era file and the per-season files
(`logs1520.csv`: `Team` = full mascot name, no URL column; per-season
files: `Team` = school name, `TeamFull` = mascot name, `URL` = CBR
school page) — consumers must not assume one schema; the manifest
records the difference per file.

## 7. Fixture-derivation proof — three-way agreement demonstrated

`derive_three_way_proof.py` (this packet) derives fixtures from the
pinned CBR bytes and checks a declared sample three ways; the full
machine-readable result is `three_way_proof_result.json`. Every
input byte stream is hash-verified against its pin before use (this
manifest for the CBR files, PR #2867's for the hoopR schedules; the
Torvik files sit at the PR #2832 pinned commit, morning-of rule
unchanged).

- **Derivation.** Each row's school is resolved to the canonical
  CBR school slug; mirror rows (same date, swapped teams, swapped
  scores) dedupe to one fixture. Across the nine seasons the
  derivation paired **48,155 fixtures** from 100,368 admitted
  team-rows, with **0 mirror-inconsistent pairs** — no CBR row pair
  disagrees with itself anywhere in the admitted scope. Rows that
  cannot pair (non-D1 opponents, ~341–507 per season) and rows with
  non-numeric scores (2 in the 2014-15 scope, 58 in 2022-23 —
  unplayed entries in CBR's logs) are counted and excluded, never
  silently resolved.
- **Name normalization is explicit and table-driven.** Canonical
  keys are CBR's own school slugs (from each row's school-page
  URL). The non-obvious surface → slug mappings live in one literal
  table, `NORMALIZATION_OVERRIDES` in `derive_three_way_proof.py`
  (41 entries, republished in `three_way_proof_result.json`):
  CBR's own display variants ("UNC", "UConn", "BYU"), CBR
  historical names ("Fort Wayne Mastodons", "LIU-Brooklyn
  Blackbirds" — programs since renamed/merged, mapped to their
  CBR slug lineage), abbreviation forms (UNLV, LSU, SMU, VCU, …),
  and the other legs' surfaces (hoopR "American University",
  "UAlbany", "Albany"; Torvik "Cleveland St.", "Texas St.",
  "Oregon St.", "Nebraska Omaha", "San Diego St.", "Albany").
  One ambiguity worth naming: Torvik carries both "San Diego"
  (University of San Diego) and "San Diego St." (San Diego State)
  — the table maps them to different slugs, exactly. Surfaces
  resolved by mirror inference instead of the table would be
  published per season in the result file; at admission the
  promoted table covers every sampled surface and the inference
  fallback fired zero times. This table is part of the design §2
  audited name-join for design evidence only; it admits no identity
  mapping (§9).
- **Declared sample.** Per season: the national championship game
  (declared by date + pair) plus the lexicographically-first
  derived fixture on the season's early and mid probe dates — the
  dates PR #2866's precondition check verified against the Torvik
  archive route (26/26). The 2019-20 season has **no championship
  game** (COVID-19 cancellation — the true record); its third
  fixture is the late-probe-date (2020-03-08) fixture, declared as
  a substitute, not disguised as a championship.
- **Result: 27/27 AGREE, 0 `SCHEDULE_DISCREPANCY`.** For every
  sampled fixture: the CBR-derived fixture (date, teams, final
  scores) matches the pinned hoopR substrate row (same fixture,
  same date, same final score; ESPN game ID recorded per fixture),
  and the morning-of Torvik archive file for that date exists and
  carries both teams. The eight championship games are among them
  (2015 Duke–Wisconsin 68–63; 2016 Villanova–North Carolina 77–74;
  2017 North Carolina–Gonzaga 71–65; 2018 Villanova–Michigan 79–62;
  2019 Virginia–Texas Tech 85–77; 2021 Baylor–Gonzaga 86–70;
  2022 Kansas–North Carolina 72–69; 2023 Connecticut–San Diego
  State 76–59) — agreeing with the source hunt's independent 10/10
  spot verification.

## 8. Precondition accounting (design PR #2843 §3; screen records PR #2866, PR #2870)

- **(a) Torvik archive files via the #2832 retrieval script at its
  pinned commit — MET** (per PR #2866; untouched by this record).
  The morning-of as-of rule of that admission binds the screen's
  use.
- **(b) Historical schedule/results assets pinned by the full-tuple
  rule of PR #2835 under a successor manifest — SATISFIED** by
  PR #2867 (merged).
- **(c) The §2 three-way fixture agreement — SATISFIABLE BY THIS
  MANIFEST** (on merge, after independent review). The CBR leg that
  PR #2867 recorded as `REFUSED_HTTP_403_NOT_PINNED` and PR #2870
  adjudicated as the screen's sole remaining blocker is pinned
  here by full tuple from a lawful mirror with documented
  provenance (§1), and §7 demonstrates the agreement mechanism
  end-to-end on a declared sample. **Conclusion: with this manifest
  merged, every §3 data pin is in place and the
  CBB_TORVIK_EFFICIENCY_V1 design screen may run exactly as
  designed**, reading the CBR leg from these pinned bytes under
  source_id `CBR_SCHEDULE_MIRROR_MATTWAITE_V1`, with the design's
  `SCHEDULE_DISCREPANCY` exclusion-and-logging semantics unchanged,
  and with CBR's §2 role limits unchanged (cross-check / reference
  only — not a ratings input, not a baseline, not an identity
  admission).

## 9. Identity crosswalk and Illinois exclusion — unchanged

This manifest pins CBR-mirror schedule bytes only. The ESPN ↔
Torvik ↔ NCAA identity crosswalk remains **OPEN — not admitted**
(PR #2835 §4): provider crosswalk matches are confidence-scored, no
NCAA game-ID column was observed, and name-only joins are refused
outside the design screen's own audited, design-evidence-only
expedient (PR #2843 §2). The §7 proof's normalization is part of
that expedient; nothing in this record admits an identity mapping.

CBB modeling scope **excludes Illinois college teams** (college only;
Illinois professional teams in other sports are in scope). The design
screen's conservative name/conference over-exclusion (PR #2843 §2)
remains the only design-stage expedient; the production ID-based,
fail-closed exclusion still depends on the crosswalk admission.
KenPom data enters nowhere, in any leg: **KenPom is NOT ADMITTED**
(paid; owner ruling), and no `kp_*` identifier may be used to fetch
or join KenPom data products.

## 10. Refusals

`SOURCE_UNAVAILABLE`, `ASSET_MISSING` (commit/path not found),
`SIZE_MISMATCH`, `SOURCE_CHANGED_AFTER_SNAPSHOT` (size, SHA-256 or
git-blob-SHA drift vs this manifest), `SCHEMA_INVALID`,
`OFF_PIN_SCOPE` (any read of `logs1520.csv` outside 2014-15 →
2017-18, or any use of the rejected `cbblogs*` composites as
admitted bytes), `IDENTITY_UNVERIFIED` (any join without an admitted
crosswalk), `ILLINOIS_COLLEGE_BLOCKED`.

## 11. What this admission does NOT do

- It does **not** run the CBB_TORVIK_EFFICIENCY_V1 design screen,
  fit any parameter, or produce any screen verdict. The screen is a
  separate act under PR #2843 §3, run on these pins (this record's
  §8 conclusion is that it *may* now run, not that it *has*).
- No CBB engine, freeze, or forward clock is created; no threshold
  changes. The pinned seasons are **design data** — several were
  visible to earlier CBB exploration — and can never later be
  presented as untouched validation. The forward prereg's data
  gates (PR #2843 §5) are entirely unaffected: the live-season
  Torvik route governs forward capture separately, and the
  crosswalk admission remains open.
- Verification accrues **forward only**, from admitted pregame
  captures, under a family's own preregistration. PAPER / research
  only: 0u, no staking, no wager execution.

## 12. Owner / reviewer decisions still required

1. Accept this DESIGN-only successor admission (merge of this PR
   after Rocky review) — this is what makes design precondition (c)
   satisfiable and unblocks the §3 screen run as a separate act.
2. Separately (unchanged from PR #2835 / PR #2867): the crosswalk
   admission — a forward-prereg gate, not a screen gate.
3. If the §2 authorization posture for the mirror (§2 of this
   record) is rejected, the fallback design amendment must be an
   explicit owner decision; the ranked options are documented in
   the source-hunt report and summarized in §2 above.
