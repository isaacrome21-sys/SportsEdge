# CBB_TORVIK_EFFICIENCY_V1 design screen — ATTEMPT 3 report

**Verdict: NOT_EXECUTABLE — `AS_OF_PREMISE_FAILURE`.**
**No fitting was performed; no DESIGN_PASS / DESIGN_FAIL is recorded;
the family's state is unchanged.** Date: 2026-10-28. Design:
`research/nba_cbb_activation_20261028/CBB_SIDES_TOTALS_DESIGN_AND_PREREG_DRAFT.md`
(PR #2843), screen spec §3, fixture gate §2, construction §1. Records
of attempts 1–2: `SCREEN_REPORT.md` and `SCREEN_REPORT_ATTEMPT2.md`
in this directory (PRs #2866 / #2870). This attempt is the first with
all three **data pins** satisfiable — and it stops on something the
pin checks cannot see: **the pinned Torvik archive files are
end-of-day, not morning-of.** The file for date D already reflects
games played on D, contradicting the design's §1 premise ("the
archive file for D is the rating as of the morning of D") and the
PR #2832 admission's binding as-of rule 2 ("Results of games played
on D are first reflected in the archive for D+1 or later"). Scoring
on file D would be lookahead; silently substituting file D−1 would
be exactly the undeclared carry-forward the admission's rule 4
forbids ("never substituted from D−1 or D+1 silently; any
carry-forward must be declared in the consuming design, with its own
review"). Neither is an executor's choice. §6 lists the governed
unblocks.

## 1. Verdict per criterion (design §3)

Design pass requires CI upper bound < 0 against **both** baselines
on **both** legs. No criterion was run:

| # | Criterion | Result |
|---|---|---|
| 1 | Spread MAE CI upper < 0 vs naive league-mean | **NOT RUN** — `AS_OF_PREMISE_FAILURE` |
| 2 | Spread MAE CI upper < 0 vs §1 simple ratings baseline | **NOT RUN** — `AS_OF_PREMISE_FAILURE` |
| 3 | Total MAE CI upper < 0 vs naive league-mean | **NOT RUN** — `AS_OF_PREMISE_FAILURE` |
| 4 | Total MAE CI upper < 0 vs §1 simple ratings baseline | **NOT RUN** — `AS_OF_PREMISE_FAILURE` |

n scored: none. (The fixture universe *was* built — §5 — because the
§2 gate never touches ratings; its counts are valid and are the
attempt's positive record.)

## 2. Preconditions — pins verified, premise failed

Verified by `verify_preconditions_attempt3.py` in this directory
(re-runnable; supersedes the attempt-1 script, whose verdict line
keys on (b) alone and is wrong on current main, and the attempt-2
script). Exit 2, printed verdict `NOT_EXECUTABLE`:

- **(a) Torvik archive route — pins MET, as-of semantics FAILED.**
  Both PR #2832 admission samples re-pulled at pinned commit
  `46d1036443ca452fdd1c6cf25cf5dff50de68337` reproduce byte-identically
  (2022-01-13: 58,716 B, 358 rows, sha256 `4de4761c…`; 2023-03-12:
  60,010 B, 363 rows, sha256 `9524481d…`); 26/26 early/mid/late
  season probes return valid morning-of-labelled files. But the
  declared-witness as-of probe (§3 below) fails on every witness.
- **(b) hoopR schedules — MET.** All 18 assets in the PR #2867
  successor manifest (9 CSV + 9 parquet, 2015–2023) hash-verified
  against the kept bytes before use: **18/18 match** (SHA-256 + size).
- **(c) CBR mirror — MET.** All 6 files in the PR #2871 successor
  manifest hash-verified before use: **6/6 match** (SHA-256 + size +
  git blob SHA recomputed from the bytes). Admitted scopes respected
  throughout: `logs1520.csv` read for 2014-15 → 2017-18 only;
  2018-19 from `logs19.csv`; per-season files thereafter.

## 3. The as-of evidence (declared witnesses)

Game dates and results are from the pinned hoopR substrate; ratings
and records are from the pinned-commit archive files themselves.

| Witness | Morning-of requires | File shows |
|---|---|---|
| Duke, file 2014-11-14 (opener played ON 11-14: Presbyterian 44 @ Duke 113) | record 0-0 | **1-0** |
| Kentucky, file 2014-11-14 (opener ON 11-14: Grand Canyon 45 @ Kentucky 85) | record 0-0 | **1-0** |
| Wisconsin, file 2014-11-14 (opener ON 11-14: Northern Kentucky 31 @ Wisconsin 62) | record 0-0 | **1-0** |
| Purdue, file 2023-03-12 (Big Ten final played ON 03-12; 28-5 before, 29-5 after) | record 28-5 | **29-5** |

The ratings move with the same-day games, not just the record
column: Wisconsin's `adj_d` is 90.405 in the 2014-11-13 file
(preseason, 0-0) and **89.118 in the 2014-11-14 file** — the
improvement a 62-31 defensive performance produces — while the
2014-11-15 file, after a day Wisconsin did not play, sits at 89.133.
Kentucky's `adj_o`: 117.724 (11-13) → 117.434 (11-14, its opener
day) → 117.442 (11-15, idle). Duke's record across the three files:
0-0 → 1-0 → 2-0, the second win being its 2014-11-15 game — i.e.
each file D is the state **after** D's games, in both the
backfilled era (2014-15) and the recent era (2022-23). In every
probed case the pattern is identical; no contrary case was found.

## 4. How this surfaced — the VOID diagnostic

During the attempt, the scoring stage was executed once,
diagnostically, on file-D inputs (the runner's pre-guard build; the
gate/universe code is byte-identical to this PR's). It produced
pooled candidate spread MAE **8.007** and a nominal four-criterion
pass — numbers no true pregame CBB model achieves (honest pregame
margin MAE is ~10.5; the same run's naive constant baseline scored
11.049 and the simple baseline 8.011, the whole table shifted by
the leak). The anomaly triggered the as-of audit in §3. **These
numbers are lookahead-contaminated and VOID: they are not screen
results, no DESIGN_PASS is recorded, and they appear here only as
the evidence that caught the premise failure.** The runner in this
PR now carries the as-of guard: it builds the universe, runs the
witness probe, and refuses (exit 2) before any fitting while the
probe fails.

## 5. Fixture universe — built, counted, leak-free

The §2 gate (Illinois exclusion first, then three-way agreement)
never reads a rating; its accounting stands. Universe build over
the nine design seasons, from 52,126 hoopR substrate rows:

| Season | hoopR rows | Illinois excl. | CBR-leg losses* | Passing CBR leg | Torvik-leg losses | **Agreed** |
|---|---:|---:|---:|---:|---:|---:|
| 2014-15 | 5,932 | 362 | 984 | 4,586 | 1,597 | **2,989** |
| 2015-16 | 5,893 | 348 | 951 | 4,594 | 1,558 | **3,036** |
| 2016-17 | 5,960 | 367 | 971 | 4,622 | 1,531 | **3,091** |
| 2017-18 | 6,003 | 359 | 982 | 4,662 | 1,579 | **3,083** |
| 2018-19 | 6,049 | 367 | 981 | 4,701 | 1,589 | **3,112** |
| 2019-20 | 5,767 | 355 | 943 | 4,469 | 1,500 | **2,969** |
| 2020-21 | 4,285 | 260 | 733 | 3,292 | 1,110 | **2,182** |
| 2021-22 | 5,976 | 357 | 1,053 | 4,566 | 1,526 | **3,040** |
| 2022-23 | 6,261 | 363 | 1,135 | 4,763 | 1,692 | **3,071** |
| **Total** | **52,126** | **3,138** | **8,733** | **40,255** | **13,682** | **26,573** |

\* CBR-leg losses = `SCHEDULE_DISCREPANCY` at the CBR stage:
`NAME_UNRESOLVED` 8,638 pooled (a hoopR team surface the published
normalization cannot resolve — overwhelmingly non-D1 opponents with
no CBR page, plus ESPN surface forms the table lacks, e.g. "Miami",
"San José State", "UMass Lowell", "McNeese", "Hawai'i",
"St. Thomas-Minnesota"); `CBR_FIXTURE_NOT_FOUND` 64;
`SCORE_MISMATCH_CBR_VS_HOOPR` 31; `CBR_MIRROR_CONFLICT` 0. The CBR
derivation itself (per season, in the results JSON) paired
5,499 / 5,516 / 5,535 / 5,540 / 5,603 / 5,328 / 3,944 / 5,475 /
5,715 fixtures with **0 mirror-inconsistent pairs**, replicating
PR #2871's derivation counts exactly.

Torvik-leg losses are dominated by `TORVIK_TEAM_NOT_CARRIED`
(13,557 pooled): Torvik's own surface forms that the published
41-entry `NORMALIZATION_OVERRIDES` table plus the legs' harvested
surface tables cannot resolve — above all Torvik's systematic
"X St." abbreviations (86 of 363 team rows unresolved on the
2023-01-15 file: "Iowa St.", "Ohio St.", "Kansas St.",
"Mississippi St.", …; the table carries only five such forms).
Per the attempt's binding instruction, **no new normalization was
invented**: a fixture needing a mapping the published table lacks
is excluded and logged. Consequence, stated plainly: the admitted
universe (26,573 fixtures) is the **name-stable subset** of the
schedule — it over-represents programs whose names are identical
across ESPN, Torvik and CBR — and any future run under an amended
convention inherits that selection. `TORVIK_MORNING_OF_NO_DATA`:
125, all on three dates (next bullet).

**Secondary finding — bounded schema drift.** The archive files
for 2022-11-07, 2022-11-08 and 2022-11-09 use a different layout
(column names `rec` / `proj_rec` / `proj_conf_rec`, **no
`adj_tempo` column at all**); the documented schema resumes
2022-11-10. PR #2832 recorded only the leading-index-column drift.
The 125 fixtures on those dates are excluded in the universe build
as NO_DATA — under the design they could not supply a totals input
in any case.

## 6. Governed unblocks (not executed here)

1. **Design amendment declaring the input convention** — e.g. the
   design adopts "the archive file for D−1 is the morning-of rating
   for games on D" (equivalently: file D is read as the pre-game
   snapshot for D+1). This is the carry-forward PR #2832 rule 4
   reserves to a declared amendment **with its own review**. The
   witnesses suggest it is mechanically coherent (the preseason
   file exists for openers: the 2014-11-13 file is 0-0-clean), and
   the screen's mechanics, baselines and bar would run unchanged
   on the declared convention — but the amendment, and the choice,
   belong to the owner/reviewer, not to this attempt.
2. **Admission of a genuinely morning-of ratings source** (none is
   currently admitted for 2014-15 → 2022-23).
3. Flag for the reviewer, untouched here: the **live-season Torvik
   route (PR #2841)** that governs forward CBB capture deserves the
   same declared-witness as-of probe before any forward reliance;
   this attempt audited only the pinned historical archive.

## 7. Readings taken (design ambiguities)

Recorded for the future amended run; none was allowed to widen any
gate during this attempt:

1. **Walk-forward window:** §3 fits parameters "on seasons strictly
   before the scored season"; no admitted season precedes 2014-15,
   so 2014-15 is the initial fitting window and scored seasons
   would be 2015-16 → 2022-23.
2. **"Blend" of `adj_tempo`** (§1) read as the arithmetic mean of
   the two teams' values.
3. **League mean efficiency** (§1) read as the mean of `adj_o` over
   the morning-of file as published; the §1 simple baseline's
   no-tempo-interaction totals use the file's mean `adj_tempo`.
4. **Simple ratings baseline** read as the §1 ablation: the same
   expected-points formula with league-mean tempo and a **fixed**
   home-court constant (estimated once on the 2014-15 window, held
   fixed) — the candidate's claimed additions are exactly
   (a) per-season home-court estimation and (b) the tempo blend.
5. **Naive league-mean baseline** read as the prior seasons' mean
   actual margin (spread leg) and mean actual total (totals leg).
6. **Home-court estimator:** mean of (actual margin − neutral-model
   margin) over prior seasons' non-neutral agreed fixtures.
7. **Bootstrap:** percentile 95% CI, 10,000 season-block resamples
   over the scored seasons, seed 20261028.
8. **`barthag`** is listed among §1's inputs but no §1 mechanic
   consumes it; read as part of the archive row taken, not a
   formula input.
9. **Spread→probability map** is part of the construction but §3's
   bar names only spread/total MAE; it would be fitted per protocol
   and recorded as diagnostics, never scored.
10. **Name resolution** = PR #2871's published
    `NORMALIZATION_OVERRIDES` (41 entries) + the legs' own surface
    tables harvested from the pinned bytes; **no mirror inference**
    (PR #2871's full derivation records it firing zero times, so
    this changes no derivation outcome — confirmed by §5's exact
    replication of its fixture counts).
11. **Illinois exclusion** (applied first): the 13 Illinois D1
    programs as CBR slugs (Bradley, Chicago State, DePaul, Eastern
    Illinois, Illinois, Illinois-Chicago, Illinois State,
    Loyola-IL, Northern Illinois, Northwestern, Southern Illinois,
    Southern Illinois-Edwardsville, Western Illinois) **or** any
    team surface containing "Illinois" — §2's conservative
    over-exclusion; 3,138 fixtures removed, surfaces listed per
    season in the results JSON.

## 8. Files in this PR

- `SCREEN_REPORT_ATTEMPT3.md` — this report.
- `screen_result_attempt3.json` — machine-readable record: pin
  verification summary, the refusal with its witnesses, the full
  per-season fixture-universe and discrepancy accounting, and all
  four criteria marked `NOT_RUN`. It contains **no MAEs and no
  pass/fail** — none were validly computed.
- `verify_preconditions_attempt3.py` — the re-runnable attempt-3
  verifier (pins (a)/(b)/(c) **and** the as-of probe; verdict
  `NOT_EXECUTABLE`, exit 2). Supersedes the attempt-1 and attempt-2
  scripts, which are left unedited as their attempts' records.
- `run_screen_attempt3.py` — the screen runner with the as-of
  guard: it reproduces the §5 universe counts exactly and refuses
  before any fitting while the probe fails.

Family state after attempt 3: **unchanged** — construction designed,
screen specified, **three attempts recorded NOT_EXECUTABLE**
(attempt 1: pin (b) missing; attempt 2: pin (c) missing; attempt 3:
the (a) leg's morning-of premise fails on the pinned bytes). No
freeze eligibility is earned or claimed. The screen can run
exactly as designed the moment a §6.1 amendment declares the input
convention — the universe, the gate and the guard are all in place
for that run.
