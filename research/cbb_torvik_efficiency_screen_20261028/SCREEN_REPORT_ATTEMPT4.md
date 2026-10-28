# CBB_TORVIK_EFFICIENCY_V1 design screen — ATTEMPT 4 report

**Verdict: DESIGN_PASS** — all four design §3 criteria pass under the
amended input convention. **One leg passes by a negligible margin and
is disclosed as such in §3 — read it before quoting this verdict.**
**No fitting discretion was exercised after seeing results; no
criterion, threshold, or leg was edited, lowered, or reinterpreted.**
Date: 2026-10-28. Base main head: `dc7b6fa2d625dc16215285479b934cedc6b9ce62`.

Design: `research/nba_cbb_activation_20261028/CBB_SIDES_TOTALS_DESIGN_AND_PREREG_DRAFT.md`
(PR #2843), screen spec §3, fixture gate §2, construction §1 — **as
amended by `AMENDMENT_1.md` in that directory (merged PR #2883)**,
which declares the PRIOR-SNAPSHOT convention for the Torvik input
only:

> For games played on date D, the model's BartTorvik input is the
> archive file dated **D−1** — the last end-of-day snapshot strictly
> before D. If the file dated D−1 does not exist on the admitted
> route, the fixture is **NO_DATA** — never substituted from D−2 or D.

Records of attempts 1–3: `SCREEN_REPORT.md` (PR #2866, NOT_EXECUTABLE
on pin (b)), `SCREEN_REPORT_ATTEMPT2.md` (PR #2870, NOT_EXECUTABLE on
pin (c)), `SCREEN_REPORT_ATTEMPT3.md` (PR #2873, NOT_EXECUTABLE —
`AS_OF_PREMISE_FAILURE`: the pinned archive files are end-of-day, not
morning-of, so scoring on file D would have been lookahead). Attempt
3's pre-guard diagnostic numbers (pooled spread MAE 8.007 on file-D
inputs) remain **VOID** and are not used anywhere in this attempt.

**What DESIGN_PASS means, by the design's own terms (§3):** this
screen is DESIGN EVIDENCE ONLY; it can never validate the family. A
design pass earns only freeze *eligibility* for the §5 forward
preregistration — it is not a freeze, not a counting authorization,
and it does not change the family's recorded state. The §5 forward
prereg remains blocked by its own data gates (identity crosswalk
OPEN; capture delivery), which this historical screen does not cure.

## 1. Preconditions — all met, as amended

Verified by `verify_preconditions_attempt4.py` in this directory
(re-runnable; exit 0, printed verdict `EXECUTABLE`):

- **(a) Torvik archive route — MET as amended.** Both PR #2832
  admission samples re-pulled at the pinned commit
  `46d1036443ca452fdd1c6cf25cf5dff50de68337` reproduce
  byte-identically (2022-01-13: 58,716 B, sha256 `4de4761c…`;
  2023-03-12: 60,010 B, sha256 `9524481d…`); 26/26 early/mid/late
  season probes return valid files; **9/9 opener D−1 probes** — the
  prior-snapshot file for each season's opening game date exists on
  the admitted route; and the **prior-snapshot witness probe passes
  4/4**: Duke / Kentucky / Wisconsin show 0-0 in the 2014-11-13 file
  (their openers were played ON 2014-11-14) and Purdue shows 28-5 in
  the 2023-03-11 file (the Big Ten final was played ON 2023-03-12
  at 28-5 before the game). Amendment 1's own probe suite verified
  the convention 19/19 (`PRIOR_SNAPSHOT_VERIFIED`, PR #2883); the
  runner additionally re-probes these witnesses against the files
  it actually reads, before any fitting (§4).
- **(b) hoopR schedules — MET.** All 18 assets in the PR #2867
  successor manifest hash-verified against the kept bytes before
  use: **18/18 match** (SHA-256 + size).
- **(c) CBR mirror — MET.** All 6 files in the PR #2871 successor
  manifest hash-verified before use: **6/6 match** (SHA-256 + size
  + git blob SHA). Admitted scopes respected throughout:
  `logs1520.csv` read for 2014-15 → 2017-18 only; 2018-19 from
  `logs19.csv`; per-season files thereafter.

## 2. Fixture universe — rebuilt under the amended §2 Torvik leg

The §2 gate (Illinois exclusion first, then three-way agreement)
was rebuilt with the Torvik leg reading on **file D−1 existence**
(Amendment 1 §5); the gate's structure is unchanged. Universe build
over the nine design seasons, from 52,126 hoopR substrate rows:

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
| 2022-23 | 6,261 | 363 | 1,135 | 4,763 | 1,712 | **3,051** |
| **Total** | **52,126** | **3,138** | **8,733** | **40,255** | **13,702** | **26,553** |

\* CBR-leg losses are identical to attempt 3, as they must be (the
hoopR and CBR legs are untouched by the amendment): `NAME_UNRESOLVED`
8,638 pooled; `CBR_FIXTURE_NOT_FOUND` 64; `SCORE_MISMATCH_CBR_VS_HOOPR`
31; `CBR_MIRROR_CONFLICT` 0. The CBR derivation again paired its
fixtures with 0 mirror-inconsistent pairs, replicating PR #2871's
derivation counts exactly (per-season detail in the results JSON).

**Delta vs attempt 3 (26,573 → 26,553, −20, all in 2022-23):**
Torvik-leg losses are `TORVIK_TEAM_NOT_CARRIED` 13,550 pooled
(attempt 3: 13,557) and `TORVIK_PRIOR_SNAPSHOT_NO_DATA` **152**
(attempt 3, as `TORVIK_MORNING_OF_NO_DATA`: 125). The NO_DATA
increase is the declared drift-schema shift (Amendment 1 §5): the
archive files for 2022-11-06/07/08/09 use the drift layout with **no
`adj_tempo` column**, and under the convention those are exactly the
files read for game dates **2022-11-07…10**, so fixtures on those
four game dates are NO_DATA — the attempt-3 treatment, shifted one
day; no tempo was substituted or imputed. Fetch log for the run:
1,243 game dates needing input → 1,243 prior-snapshot files needed,
**1,239 fetched/cached OK, 0 missing (404), 4 schema-invalid** (the
four drift files). No game date's D−1 file was missing anywhere in
the design span.

The attempt-3 selection disclosure carries unchanged: the admitted
universe is the **name-stable subset** of the schedule (Torvik's
systematic "X St." surface forms remain unresolvable under the
published 41-entry `NORMALIZATION_OVERRIDES` table — no new
normalization was invented for this attempt), and it
over-represents programs whose names are identical across ESPN,
Torvik and CBR.

## 3. Criteria (design §3) — all four run, all four pass

Design pass = paired season-block bootstrap CI upper bound < 0
against **both** baselines on **both** legs (10,000 resamples,
seed 20261028; walk-forward by season; 2014-15 is the fitting
window; scored seasons 2015-16 → 2022-23, **n = 23,564 fixtures**).

| # | Criterion | Mean paired diff (MAE points) | 95% CI | Upper < 0 |
|---|---|---:|---:|:--:|
| 1 | Spread MAE vs naive league-mean | −2.145 | [−2.317, −1.972] | **PASS** |
| 2 | Spread MAE vs §1 simple ratings | **−0.005** | [−0.008, **−0.001**] | **PASS — marginal** |
| 3 | Total MAE vs naive league-mean | −1.875 | [−2.561, −1.353] | **PASS** |
| 4 | Total MAE vs §1 simple ratings | −0.899 | [−1.062, −0.764] | **PASS** |

Pooled MAEs: candidate spread **8.899** / total **13.812**; naive
11.045 / 15.687; simple ratings 8.904 / 14.710.

**The marginal leg, stated plainly.** Criterion 2 passes the bar as
written — CI upper bound −0.0009 < 0 — but the candidate's spread
advantage over the simple ratings baseline is **0.005 MAE points**,
practically nil. That is mechanically expected, and the design
says why: on the spread leg the candidate's only addition over the
§1 ablation is per-season home-court estimation (the tempo blend,
its other claimed addition, acts on totals only — and there it
pays clearly, criterion 4). Per-season candidate spread MAE is
worse than the simple baseline's in 2016-17 (8.707 vs 8.701) and
within ±0.011 in every other scored season; the pooled sign is
consistently, trivially negative. **No re-run, re-seed, or tuning
followed this result** — the bootstrap seed and procedure are the
preregistered readings (attempt 3, reading 7), and the criterion is
the criterion. But no reader should mistake criterion 2 for
evidence of a meaningful spread edge over the simple baseline; the
screen's substantive findings are criteria 1, 3 and 4.

Per-season MAE (candidate / naive / simple; spread · total):

| Season | n | Candidate | Naive | Simple |
|---|---:|---|---|---|
| 2015-16 | 3,036 | 8.823 · 14.139 | 11.203 · 18.095 | 8.829 · 15.159 |
| 2016-17 | 3,091 | 8.707 · 13.912 | 11.247 · 16.247 | 8.701 · 15.268 |
| 2017-18 | 3,083 | 8.700 · 14.206 | 10.890 · 16.132 | 8.702 · 15.147 |
| 2018-19 | 3,112 | 8.969 · 14.333 | 11.149 · 15.691 | 8.979 · 15.201 |
| 2019-20 | 2,969 | 9.028 · 13.730 | 10.877 · 15.356 | 9.037 · 14.487 |
| 2020-21 | 2,182 | 9.226 · 13.425 | 11.072 · 14.518 | 9.233 · 14.205 |
| 2021-22 | 3,040 | 8.804 · 13.275 | 11.070 · 14.409 | 8.809 · 13.885 |
| 2022-23 | 3,051 | 9.036 · 13.345 | 10.850 · 14.698 | 9.042 · 14.158 |

Fitted walk-forward parameters are recorded per scored season in
the results JSON (candidate home-court term ranges 3.246–3.376
across scored seasons vs the simple baseline's fixed 3.376,
estimated once on the 2014-15 window; spread→probability map fitted
per protocol and recorded as diagnostics, never scored — reading 9).

**Leak comparison, for the record.** Attempt 3's VOID file-D
diagnostic produced pooled candidate spread MAE 8.007 — 0.89 points
flattered against this attempt's honest D−1 figure of 8.899 — while
its rating-free naive leg (11.049) reproduces here almost exactly
(11.045, the small delta being the −20-fixture universe change).
The D-to-D−1 degradation is the lookahead attempt 3 caught, now
removed by the declared convention rather than by silence.

## 4. Self-audit (performed before this report was written)

- **Lookahead spot-check (independent of the scoring path).** For
  the 2023-03-12 Big Ten final (Purdue 67, Penn State 65, pinned
  hoopR substrate), the runner's parsed input for Purdue is exactly
  the **2023-03-11** file's row — adj_o 119.862…, adj_d 94.620…,
  adj_tempo 64.024…, record 28-5 — and **not** the 2023-03-12
  file's row (119.500…, 94.254…, record 29-5, which already
  contains the final's result). The unit tests additionally pin
  that a file whose rows carry a different date than the file
  requested parses to a refusal, and that a drift-layout file
  without `adj_tempo` is NO_DATA.
- **Determinism.** The full runner was executed twice; the two
  `screen_result_attempt4.json` outputs are identical and the
  printed summaries match exactly.
- **Guard.** The runner's prior-snapshot probe ran before any
  fitting on the executed path (its witnesses are embedded in the
  results JSON); had it failed, the runner would have refused with
  `PRIOR_SNAPSHOT_PREMISE_FAILURE` and exit 2, before scoring.
- **Tests.** `tests/test_cbb_torvik_screen_attempt4.py`: 10 passed
  (D−1 arithmetic incl. month/year/leap boundaries; parse-by-own-date;
  date-mismatch refusal; drift NO_DATA; probe pass/fail; construction
  and bootstrap arithmetic). Family manifest tests re-run with this
  PR — see the PR description.

## 5. Readings taken (design ambiguities)

Attempt 3's ten recorded readings (its report §7) are inherited
unchanged, except where Amendment 1's convention supersedes a
vintage assumption (reading 3's "morning-of file" now reads
"prior-snapshot file" — the league aggregates are computed over the
D−1 file as published). No new reading was introduced by this
attempt; the drift-NO_DATA treatment is Amendment 1 §5's declared
mechanical consequence, applied as attempt 3 applied it to file D.

## 6. Files in this PR

- `SCREEN_REPORT_ATTEMPT4.md` — this report.
- `screen_result_attempt4.json` — machine-readable record: pin
  verification summary, the prior-snapshot probe with its
  witnesses, the full per-season fixture-universe and discrepancy
  accounting, fitted parameters per scored season, per-season and
  pooled MAEs, and all four criteria with CIs and pass flags.
- `run_screen_attempt4.py` — the amended-convention runner
  (attempt 3's runner with the Torvik leg re-pointed to file D−1
  and the as-of guard replaced by the prior-snapshot guard;
  attempt 1–3 files are left unedited as their attempts' records).
- `verify_preconditions_attempt4.py` — the re-runnable attempt-4
  verifier (pins (a)/(b)/(c), opener D−1 existence probes, and the
  prior-snapshot witness probe; verdict `EXECUTABLE`, exit 0).
- `tests/test_cbb_torvik_screen_attempt4.py` — offline guards for
  the attempt-4 mechanics (10 tests).

Family state after attempt 4: construction designed, screen
specified, attempts 1–3 recorded NOT_EXECUTABLE, **attempt 4
DESIGN_PASS under the Amendment 1 prior-snapshot convention** —
freeze *eligibility* for the §5 forward preregistration only, under
the design's own terms. Nothing was frozen; no row counts anywhere.
PAPER / research only: 0u, no staking, no wager execution. This PR
is a draft for Rocky's clearance.
