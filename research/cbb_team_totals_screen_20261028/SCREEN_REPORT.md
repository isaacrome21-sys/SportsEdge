# SCREEN REPORT — CBB team totals (third leg) — PRIOR-SNAPSHOT RERUN

**Status: SCREEN EXECUTED — DESIGN EVIDENCE ONLY — NO CLOCK —
NOTHING FROZEN.** Date: 2026-10-28. Family: CBB team totals.
Evidence class: **DESIGN EVIDENCE ONLY — not validation** (parent
design §3). Machine-readable record: `screen_result.json` in this
directory. Runner: `run_team_totals_screen.py`; construction:
`cbb_team_totals.py`.

Designs of record (PR #2843, merged):
`CBB_TEAM_TOTALS_1H_DESIGN.md` §1 and
`CBB_SIDES_TOTALS_DESIGN_AND_PREREG_DRAFT.md` §§1–3. Input
convention of record: **Amendment 1 (PR #2883, merged)** —
`research/nba_cbb_activation_20261028/AMENDMENT_1.md`.

## Verdict

| Family / criterion | Verdict |
|---|---|
| Team totals — team-points MAE vs (i) naive team-mean, CI upper < 0 | **PASS** — CI upper **−1.1011** |
| Team totals — team-points MAE vs (ii) simple ratings baseline's team points, CI upper < 0 | **PASS** — CI upper **−0.3242** |
| **CBB team totals design screen** | **DESIGN_PASS** (the leg's own bar: CI upper < 0 vs BOTH baselines) |
| CBB first-half lines | **NOT_EXECUTABLE** — `PBP_PREREQUISITE_MISSING` (unchanged; out of scope for this rerun, not attempted) |

DESIGN_PASS is design evidence only. It is not validation, not a
verified status, not a freeze, and it starts no clock. Any forward
preregistration for this construction needs its own terms and its
own review (Amendment 1 §6).

Pooled team-points MAE (23,564 scored fixtures, 47,128
team-games): **candidate 8.3411**, naive team-mean **9.6813**,
simple ratings baseline **8.7226**.

## 1. What changed since the first run — and what did not

The first run of this screen (PR #2882) returned
**NOT_EXECUTABLE — `AS_OF_PREMISE_FAILURE`**: the design's
morning-of premise is false on the pinned bytes (the Torvik
archive files are end-of-day snapshots; declared witnesses failed
10/10 and the opening-day audit failed all nine seasons). That
record stands unaltered for that premise.

Amendment 1 (PR #2883, merged) declared the governed unblock —
the **PRIOR-SNAPSHOT convention**, verbatim:

> "For games on date D, the model's Torvik input is the archive
> file dated D−1 — the last end-of-day snapshot strictly before
> D; if file D−1 does not exist, the fixture is NO_DATA, never
> substituted."

This rerun applies exactly that convention to the Torvik leg of
the existing construction and rebuilds the fixture universe on
file D−1 existence. **Nothing else changed:** the construction
formula, both baselines, the seasons (2014-15 → 2022-23), the
walk-forward protocol, the bootstrap constants (10,000 resamples,
seed 20261028), the Illinois-college exclusion, and both screen
criteria are byte-for-byte the design's. No market baseline was
added — the design names none for this screen (the market leg is
a forward term gated on a freeze that does not exist). No tuning
followed the result; the numbers below are the first and only
scoring run under this convention (executed twice — §5).

Provenance note: at this rerun's dispatch, the packet files
themselves still sit on PR #2882's open branch — they are not yet
on main. This branch therefore carries the packet onto current
main (dc7b6fa2d) with the convention fix applied; if #2882 lands
first, this PR reduces to the convention delta and the rerun
record.

## 2. Premise audit under the convention (before any scoring)

The runner re-probes the convention for this family before any
fitting or scoring (Amendment 1 verified it 19/19 for the parent
screen; this is the team-totals leg's own re-probe):

- **Declared witnesses — 10/10 PASS**, read in the D−1 files:
  Duke / Kentucky / Wisconsin / Kansas / Michigan St. / North
  Carolina / UCLA all **0-0** in the 2014-11-13 file; Purdue
  **28-5** in the 2023-03-11 file (entered the 2023-03-12 Big Ten
  final at 28-5); Connecticut **30-8** and San Diego St. **32-6**
  in the 2023-04-02 file (their entering records for the
  2023-04-03 national final).
- **Opening-day audit — 9/9 seasons PASS:** for every design
  season, the archive file dated the day before the season's
  first game date shows **every team at 0-0** (347–363 teams per
  file, zero exceptions).

## 3. Fixture universe (three-way §2 gate, rebuilt on D−1)

| Season | hoopR rows | Illinois excluded | Passing CBR leg | Torvik-leg losses | Agreed three-way |
|---|---|---|---|---|---|
| 2014-15 | 5,932 | 362 | 4,586 | 1,597 not carried | 2,989 |
| 2015-16 | 5,893 | 348 | 4,594 | 1,558 not carried | 3,036 |
| 2016-17 | 5,960 | 367 | 4,622 | 1,531 not carried | 3,091 |
| 2017-18 | 6,003 | 359 | 4,662 | 1,579 not carried | 3,083 |
| 2018-19 | 6,049 | 367 | 4,701 | 1,589 not carried | 3,112 |
| 2019-20 | 5,767 | 355 | 4,469 | 1,500 not carried | 2,969 |
| 2020-21 | 4,285 | 260 | 3,292 | 1,110 not carried | 2,182 |
| 2021-22 | 5,976 | 357 | 4,566 | 1,526 not carried | 3,040 |
| 2022-23 | 6,261 | 363 | 4,763 | 1,560 not carried + 152 NO_DATA | 3,051 |
| **Total** | **52,126** | **3,138** | **40,255** | **13,702** | **26,553** |

Cross-checks against the parent screen's attempt-3 accounting on
the same pinned bytes: substrate rows (52,126), Illinois
exclusions (3,138), and fixtures passing the CBR leg (40,255)
reproduce **exactly**. The agreed total differs from attempt 3's
26,573 by −20, entirely in the Torvik leg (13,702 losses here vs
13,682 there) — the expected mechanical effect of reading D−1
files (Amendment 1 §5).

Torvik fetch log: **1,239 prior-snapshot files** fetched or
served from the pinned-commit cache, **0 missing (404)**, **4
schema-invalid** — exactly the drift-layout files
**2022-11-06/07/08/09** (no `adj_tempo` column; Amendment 1 §5
records the 2022-11-06 file itself as drift-layout, with the
window shifted one day under the convention). Their fixtures are
NO_DATA: the 152 NO_DATA losses above, all in 2022-23, covering
game dates 2022-11-07…10. No file was substituted for any of
them.

## 4. Results — per-season team-points MAE

Scored seasons are 2015-16 → 2022-23 (2014-15 is the naive
baseline's initial fitting window, per the walk-forward
protocol). The candidate beats **both** baselines in **every**
scored season:

| Season | Fixtures | Candidate | Naive | Simple |
|---|---|---|---|---|
| 2015-16 | 3,036 | 8.5092 | 10.9305 | 8.9375 |
| 2016-17 | 3,091 | 8.3292 | 9.8276 | 8.9118 |
| 2017-18 | 3,083 | 8.4840 | 9.7375 | 8.8854 |
| 2018-19 | 3,112 | 8.5371 | 9.6957 | 8.9148 |
| 2019-20 | 2,969 | 8.3306 | 9.5002 | 8.6551 |
| 2020-21 | 2,182 | 8.1951 | 9.1468 | 8.5272 |
| 2021-22 | 3,040 | 8.1316 | 9.1437 | 8.3949 |
| 2022-23 | 3,051 | 8.1654 | 9.3125 | 8.4882 |
| **Pooled** | **23,564** | **8.3411** | **9.6813** | **8.7226** |

Criteria (paired season-block bootstrap, 10,000 resamples, seed
20261028, 8 season blocks; bar = CI upper bound < 0):

| Criterion | Mean paired diff | 95% CI | Pass |
|---|---|---|---|
| vs (i) naive team-mean | −1.3401 | [−1.6817, **−1.1011**] | **PASS** |
| vs (ii) simple ratings baseline | −0.3814 | [−0.4529, **−0.3242**] | **PASS** |

## 5. Verification performed by this run

- Pins verified before any use: hoopR successor manifest (PR
  #2867) **18/18** assets hash-verified; CBR mirror successor
  (PR #2871) **6/6** files hash + size + git-blob verified,
  admitted scopes only; Torvik admission samples (PR #2832)
  **2/2** re-verified byte-identical at the pinned commit
  `46d1036443ca452fdd1c6cf25cf5dff50de68337`.
- **Reproducibility:** the screen was executed twice end-to-end;
  the two `screen_result.json` outputs are identical.
- Family tests: **20 passed** (`tests/test_cbb_team_totals.py`) —
  the #2882 suite with the audit tests re-pointed at D−1 (the
  stub now proves the runner fetches D−1, never D), a
  `prior_date` arithmetic test added, and the committed-record
  test rewritten for the executed verdict. Repo CBB test surface:
  **112 passed**. Ruff gate (E9,F821,F822,F823,F811) clean.
  Stdlib only; no dependencies added.

## 6. First-half lines — unchanged, out of scope

The runner's prerequisite scan still finds no pinned hoopR
play-by-play (`load_mbb_pbp`) manifest in the repo, so 1H remains
**NOT_EXECUTABLE — `PBP_PREREQUISITE_MISSING`**, exactly as in
the first run. This rerun did not attempt the 1H family; the gap
is a separate PBP admission job. No share was invented or halved.

## 7. What this does not do

Nothing in this packet freezes terms, starts a clock, counts a
game, or changes any family's recorded state beyond recording
this design-screen result. The construction's recorded
operationalizations stand as flagged in the first run (tempo
blend = arithmetic mean; naive baseline = prior-seasons team
mean with league fallback) — neither was revisited here.
