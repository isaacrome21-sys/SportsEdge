# SCREEN REPORT — CBB_TORVIK_EFFICIENCY_V1 design screen

# VERDICT: NOT_EXECUTABLE — the screen was NOT run

**Family:** CBB sides/totals (spread, moneyline, game total).
**Construction:** `CBB_TORVIK_EFFICIENCY_V1` (design:
`research/nba_cbb_activation_20261028/CBB_SIDES_TOTALS_DESIGN_AND_PREREG_DRAFT.md`,
merged in PR #2843). **Screen:** the historical design screen of design §3 —
DESIGN EVIDENCE ONLY by the design's own terms; it can never validate the
family. Date of this report: 2026-10-28. Base main head:
`e9d0c197a16717273cc6f57176dbc5b8a3340a0b`.

No fixtures were scored, no parameters were fitted, no criteria were
relaxed, and no substitute data was used. This report proves, with
re-runnable evidence, exactly which of the design's own preconditions
holds and which one does not.

## 1. The screen as designed (design §3, extracted verbatim in substance)

- **Seasons:** the admitted archive's coverage, 2014-15 → 2022-23.
- **Construction (§1):** expected possessions = blend of the two teams'
  `adj_tempo`; expected team points = (team `adj_o` + opponent `adj_d`
  − league mean efficiency) / 100 × expected possessions, every term
  from the **morning-of** archive file for the game date D; margin =
  expected-points difference + home-court term (zero at neutral sites,
  from a venue flag in the schedule substrate — never inferred from
  team order); total = sum of expected team points; moneyline
  probability from the margin via a spread→probability map fitted on
  strictly prior seasons only.
- **Protocol:** walk-forward by season — home-court term and the
  spread→probability map fitted on seasons strictly before the scored
  season; ratings always the morning-of file for each game date.
- **Metrics and bar:** spread MAE and total MAE, candidate vs
  (i) a naive league-mean baseline and (ii) the §1 **simple ratings
  baseline** (raw efficiency differential, fixed league-average
  home-court constant, no tempo interaction for totals); paired,
  season-block bootstrap CIs. **Design pass = CI upper bound < 0
  against both baselines on both legs.** A design pass earns only
  freeze eligibility for the forward prereg (§5) and is labelled
  DESIGN_PASS, never validation. The §3 screen names no market /
  closing-line baseline — the market leg (CLV/ROI vs the DK close)
  exists only in the forward prereg, so no closing lines are required
  by the screen as written, and none were sought.
- **Illinois exclusion:** design §2 — for the screen, Illinois fixtures
  are conservatively over-excluded on name/conference match, applied
  before any fitting; an audited name-join is permitted for design
  evidence only, with the ambiguity list published and every ambiguous
  fixture excluded.
- **Data pins required BEFORE any run (design §3):**
  (a) Torvik archive files via the PR #2832 retrieval script at its
      pinned commit, one file per game date;
  (b) historical schedule/results assets from the sportsdataverse-data
      releases pinned by the full-tuple rule of PR #2835 (tag +
      release ID + asset ID + size + `updated_at` + SHA-256) **under a
      successor manifest — #2835 pinned the 2027 schedule and 2026
      player box only, so this pin is outstanding work, named in the
      design itself**;
  (c) the §2 **three-way fixture agreement** — hoopR substrate (ESPN
      game ID, date, teams, final score), Torvik archive (a morning-of
      file exists for that date and carries both teams), and College
      Basketball Reference's season schedule (same fixture, same date,
      same final score) — applied before any fitting; any disagreement
      excludes the fixture as `SCHEDULE_DISCREPANCY`.

Design §6 states the consequence plainly, and this report confirms it
is still true: *"Historical schedule/results full-tuple pin (successor
manifest to PR #2835) is outstanding — the design screen cannot run
until it lands."*

## 2. Precondition (a) — Torvik archive at the pinned commit: MET (verified-by-pull)

Route: `andreweatherman/toRvik-data` at pinned commit
`46d1036443ca452fdd1c6cf25cf5dff50de68337` (PR #2832 admission), via the
admitted retrieval script's URL pattern and validation semantics.

- The admission's two hash-pinned samples were re-pulled on 2026-10-28
  and reproduce **byte-identically**:
  - 2022-01-13: 58,716 bytes, 358 team rows, sha256
    `4de4761caf3f581c56d9587ac9deeb954556ee5a8529948d8ef5206f9dfe14ad` — MATCH.
  - 2023-03-12: 60,010 bytes, 363 team rows, sha256
    `9524481d69c7b690200299387690654091565ef1d3df774ca858749e5e1cc01c` — MATCH.
- By-date coverage was probed at three dates (early / mid / late) in
  **every** design season, 26 probes in total, each returning a valid
  file whose rows all carry the requested date (the as-of rule's
  `DATE_MISMATCH` check) and a full D1 team count:

  | Season | Probes (YYYYMMDD → team rows) |
  |---|---|
  | 2014-15 | 20141115 → 351 · 20150115 → 351 · 20150315 → 351 |
  | 2015-16 | 20151114 → 351 · 20160115 → 351 · 20160313 → 351 |
  | 2016-17 | 20161112 → 351 · 20170115 → 351 · 20170312 → 351 |
  | 2017-18 | 20171111 → 351 · 20180114 → 351 · 20180311 → 351 |
  | 2018-19 | 20181110 → 353 · 20190113 → 353 · 20190317 → 353 |
  | 2019-20 | 20191109 → 353 · 20200112 → 353 · 20200308 → 353 |
  | 2020-21 | 20201128 → 347 · 20210117 → 347 · 20210314 → 347 |
  | 2021-22 | 20211113 → 358 · 20220116 → 358 · 20220313 → 358 |
  | 2022-23 | 20221112 → 363 · 20230115 → 363 (+ pinned sample 20230312) |

  26/26 probes OK. The ratings input the screen needs exists, at the
  pinned commit, across the full design span. (Per the admission's
  license terms, no Torvik data files are committed anywhere in this
  PR — hashes and manifests only.)

## 3. Precondition (b) — historical schedule/results full-tuple pin: NOT MET (the blocker)

- PR #2835's `sample_manifest.json` pins exactly five assets:
  `mbb_schedule_2027.parquet`, `mbb_schedule_2027.csv`,
  `player_box_2026.parquet`, `mbb_schedule_crosswalk_2026.csv`,
  `mbb_team_crosswalk_2026.csv`. **No historical-season schedule or
  results asset is pinned** — nothing for any season the screen scores
  (2014-15 → 2022-23).
- A repo-wide scan (all `.json` / `.md` / `.py` / `.txt` on main
  `e9d0c197a`) for `mbb_schedule_2015` … `mbb_schedule_2023` finds
  **no pin in any manifest**; the only mentions are the design
  documents referencing the requirement itself.
- The data **exists upstream** — the `espn_mens_college_basketball_schedules`
  release of `sportsdataverse/sportsdataverse-data` lists
  `mbb_schedule_YYYY.csv/.parquet/.rds` for YYYY spanning the design
  seasons and beyond (verified-by-pull of the release asset list,
  2026-10-28). Existence is not the gap. The gap is the **pin**: that
  release is a rolling target whose assets are replaced in place (the
  PR #2835 record's central verified finding: the 2027 parquet asset
  was updated 2026-10-18, its CSV twin 2026-09-15), and the PR #2835
  pin rule makes an unpinned pull a refusal
  (`SOURCE_CHANGED_AFTER_SNAPSHOT` discipline), never a silent
  acceptance. The design adopts that rule by reference and requires
  the successor manifest *"before any run."*
- Everything the screen needs from the substrate rides on this pin:
  the fixture universe (dates, teams, final scores), the **venue
  flag** the §1 margin formula requires for neutral-site games, and
  the hoopR leg of the §2 three-way agreement. There is no pinned
  fixture to score, exclude, or agree on.

Creating that successor manifest is a separate governed admission act
(the PR #2835 pattern: its own PR, its own review), which the design
names as outstanding prerequisite work — it is not part of executing
the screen, and improvising it inside this run would breach the
design's precondition and the repo's pin discipline. It was therefore
not improvised.

## 4. Precondition (c) — three-way fixture agreement: NOT APPLICABLE until (b) lands

The agreement check operates on the pinned substrate's fixture
universe; with (b) unmet there is nothing to check agreement against.
Independently, the College Basketball Reference leg is
**documented-only** in the design ("no bytes were pulled from it for
this design"), and its season schedules for 2014-15 → 2022-23 carry no
pin either — a second, dependent gap the successor workstream must
close (pull + hash-pin per season, or an admission stating the
verification method) before a run can apply §2 as written.

## 5. Criteria — all NOT RUN

| # | Design §3 criterion (design pass requires all four) | Result |
|---|---|---|
| 1 | Spread MAE: paired season-block bootstrap CI upper bound < 0 vs naive league-mean baseline | NOT RUN — precondition (b) unmet |
| 2 | Spread MAE: CI upper bound < 0 vs §1 simple ratings baseline | NOT RUN — precondition (b) unmet |
| 3 | Total MAE: CI upper bound < 0 vs naive league-mean baseline | NOT RUN — precondition (b) unmet |
| 4 | Total MAE: CI upper bound < 0 vs §1 simple ratings baseline | NOT RUN — precondition (b) unmet |

n per season: none. n pooled: none. No DESIGN_PASS and no DESIGN_FAIL
is recorded — recording either without running the screen as designed
would fabricate a verdict.

**Family state is unchanged:** CBB sides/totals remains
DESIGN + DESIGN-SCREEN SPEC + PREREG DRAFTED, with the screen now
formally recorded NOT_EXECUTABLE on its own stated precondition. The
§5 forward prereg is unaffected by this report and remains blocked by
its own data gates (live-season Torvik route — since addressed
separately by the PR #2841 live route for forward use; identity
crosswalk OPEN; capture delivery), none of which this historical
screen could cure in any case.

## 6. What unblocks the screen (one line each)

1. A successor-manifest PR in the PR #2835 pattern pinning
   `mbb_schedule_2015` … `mbb_schedule_2023` (one format per season,
   each format pinned independently) by full tuple — tag + release
   ID + asset ID + size + `updated_at` + SHA-256 — with the assets'
   final-score and venue fields verified by pull.
2. A College Basketball Reference leg with bytes actually pulled and
   hash-pinned per season (or an admitted verification method), so
   the §2 three-way agreement can be applied as written.
3. Then the screen runs exactly as §3 specifies — walk-forward by
   season, morning-of ratings, Illinois over-exclusion first, audited
   name-join with the ambiguity list published — with no criterion
   edits.

## 7. Provenance and reproduction

- Repo / base: `isaacrome21-sys/SportsEdge` @
  `e9d0c197a16717273cc6f57176dbc5b8a3340a0b` (fresh clone).
- Design: PR #2843 (merged). Torvik admission: PR #2832 (merged),
  mirror pinned commit `46d1036443ca452fdd1c6cf25cf5dff50de68337`.
  Substrate admission: PR #2835 (merged).
- Machine-readable record: `screen_result.json` (this directory).
- Reproduction: `python3 verify_preconditions.py` (this directory,
  stdlib only) re-pulls the Torvik samples, re-probes all 26 season
  dates, re-scans the repo for a historical schedule pin, and prints
  the same verdict.
- PAPER / research only: 0u, no staking, no wager execution. Nothing
  was frozen; this PR is a draft for Rocky's clearance.
