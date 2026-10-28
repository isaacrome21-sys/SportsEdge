# SCREEN REPORT — CBB team totals (third leg) + first-half lines

**Status: DESIGN ONLY — NO CONSTRUCTION RUN — NO CLOCK — NOTHING
FROZEN.** Date: 2026-10-28. Families: CBB team totals; CBB first-half
lines (1H spread / 1H total). Evidence class: **DESIGN EVIDENCE
ONLY — not validation** (parent design §3). Machine-readable record:
`screen_result.json` in this directory. Runner:
`run_team_totals_screen.py`; construction: `cbb_team_totals.py`.

Designs of record (PR #2843, merged):
`CBB_TEAM_TOTALS_1H_DESIGN.md` and
`CBB_SIDES_TOTALS_DESIGN_AND_PREREG_DRAFT.md` §§1–3.

## Verdicts

| Family / criterion | Verdict |
|---|---|
| Team totals — team-points MAE vs (i) naive team-mean, CI upper < 0 | **NOT RUN** — screen NOT_EXECUTABLE |
| Team totals — team-points MAE vs (ii) simple ratings baseline's team points, CI upper < 0 | **NOT RUN** — screen NOT_EXECUTABLE |
| **CBB team totals design screen** | **NOT_EXECUTABLE** — refusal `AS_OF_PREMISE_FAILURE` |
| **CBB first-half lines** | **NOT_EXECUTABLE** — refusal `PBP_PREREQUISITE_MISSING` |

No DESIGN_PASS / DESIGN_FAIL is recorded for any criterion; no
fitting or scoring was performed; the families' recorded states do
not change.

## 1. What the design specifies (quoted)

Team totals (team-totals design §1):

> "Team totals need no second model: the expected team points of
> CBB_TORVIK_EFFICIENCY_V1 … *are* the team-total forecasts, home
> and away. The family therefore: **Screens inside the §3 design
> screen of the sides/totals document**, as a third leg:
> team-points MAE, candidate vs (i) a naive team-mean baseline and
> (ii) the simple ratings baseline's team points, same pins, same
> walk-forward protocol, same DESIGN-evidence label. The leg
> passes or fails on its own CI, independently of the spread/total
> legs."

Construction (parent design §1): inputs are "exactly one source:
the **morning-of BartTorvik T-Rank archive row for the game's date
D** … the archive file for D is the rating as of the morning of D;
no same-day post-game data, no later-vintage reconstruction, no
silent carry-forward (a missing file for D makes the fixture
NO_DATA)". Expected team points = (team `adj_o` + opponent `adj_d`
− league mean efficiency) / 100 × expected possessions, where
expected possessions is the blend of the two teams' `adj_tempo`.

Screen (parent design §3): seasons 2014-15 → 2022-23; walk-forward
by season; "paired, season-block bootstrap CIs"; the bar in §3's
form is "CI upper bound < 0 against *both* baselines". Fixtures
enter only on the §2 three-way agreement (hoopR substrate; Torvik
archive date coverage; College Basketball Reference season
schedules), Illinois-college fixtures excluded first.

The PR #2832 admission's binding as-of rule 2: "**No same-day
post-game data may price that day's games.** Results of games
played on D are first reflected in the archive for D+1 or later."
Rule 4: a missing file for D is `NO_DATA` — "never substituted from
D−1 or D+1 silently; any carry-forward must be declared in the
consuming design, with its own review."

**Market baseline:** the design names **none** for this family's
design screen — its screen baselines are (i) and (ii) above. The
market leg in team-totals §1 (T-1H priced, FINAL-graded, "CLV > 0
and ROI > 0") is a *forward* term, gated on the §5 data gates and
a freeze that does not exist; no market-implied split is computed
by this screen, and none was substituted for the named baselines.

## 2. What was run

Pins verified before any use (runner exit would have been a pin
refusal otherwise): hoopR successor manifest (PR #2867) **18/18**
assets hash-verified; CBR mirror successor (PR #2871) **6/6**
files hash + size + git-blob verified, admitted scopes only;
Torvik admission samples (PR #2832) **2/2** re-verified
byte-identical at the pinned commit `46d1036443ca452fdd1c6cf25cf5dff50de68337`.

The runner then audited the design's morning-of premise **before
any fitting or scoring**, two ways:

**(a) Declared witnesses** — teams whose pre-game record on a
declared date is fixed by the pinned substrates. **10 of 10 fail:**

| Case | Expected if morning-of | Observed |
|---|---|---|
| Duke, 2014-11-14 file | 0-0 | **1-0** |
| Kentucky, 2014-11-14 file | 0-0 | **1-0** |
| Wisconsin, 2014-11-14 file | 0-0 | **1-0** |
| Kansas, 2014-11-14 file | 0-0 | **1-0** |
| Michigan St., 2014-11-14 file | 0-0 | **1-0** |
| North Carolina, 2014-11-14 file | 0-0 | **1-0** |
| UCLA, 2014-11-14 file | 0-0 | **1-0** |
| Purdue, 2023-03-12 file (Big Ten final that day) | 28-5 | **29-5** |
| Connecticut, 2023-04-03 file (national final that evening) | 30-8 | **31-8** |
| San Diego St., 2023-04-03 file | 32-6 | **32-7** |

**(b) Systematic opening-day audit** — for every design season,
the archive file for the season's first game date (from the pinned
hoopR substrate) must show **every** team at 0-0 under morning-of
semantics. **All nine seasons fail**, by hundreds of teams:

| Season | Opening date | Teams in file | Teams NOT 0-0 |
|---|---|---|---|
| 2014-15 | 2014-11-14 | 351 | 226 |
| 2015-16 | 2015-11-13 | 351 | 228 |
| 2016-17 | 2016-11-11 | 351 | 226 |
| 2017-18 | 2017-11-10 | 351 | 230 |
| 2018-19 | 2018-11-06 | 353 | 188 |
| 2019-20 | 2019-11-05 | 353 | 236 |
| 2020-21 | 2020-11-25 | 347 | 186 |
| 2021-22 | 2021-11-09 | 358 | 304 |
| 2022-23 | 2022-11-07 | 363 | 326 |

**Conclusion of fact:** the PR #2832 pinned archive files are
**end-of-day** — the file for D already reflects the games played
on D (records, and with them the recomputed adj_o / adj_d /
adj_tempo the construction consumes). Forecasting a game's team
points from file D would read that game's own result: lookahead,
barred by design §1 and admission rule 2. The team-totals leg
consumes the same expected team points from the same files, so
the parent screen's `AS_OF_PREMISE_FAILURE` (attempt 3, which
reached the identical refusal on four witnesses) applies to this
family identically — here independently reproduced on ten
declared witnesses and a complete-population audit of all nine
seasons. Substituting file D−1 was **not** done: that is the
carry-forward admission rule 4 reserves to a declared design
amendment with its own review.

Sequencing note: the parent screen's attempt 3 built its fixture
universe before its probe failed; this runner audits first. Same
gate, same refusal, no fitting or scoring either way. Unlike the
parent attempt's pre-guard diagnostic, **no lookahead-contaminated
numbers were produced here at all**.

Secondary observation (recorded, not acted on): the mirror's
schema drifts — the 2022-11-07 file publishes `rec` / `proj_rec`
and **no `adj_tempo` column** (the admission's §4 schema-drift
warning; the parent's attempt-3 fetch log recorded 3
schema-invalid files). Under the admission such a file is
`SCHEMA_INVALID` for this construction regardless of the premise:
fixtures on those dates would be NO_DATA even under a cured
convention. The audit reads the record under either published
column name and records which one each file used.

## 3. The construction, as built (for the record)

`cbb_team_totals.py` implements the design exactly, constants
section-cited: expected possessions as the tempo blend
(operationalized as the arithmetic mean — the design says "blend"
without naming the operator; the parent attempt-3 record takes the
same reading; flagged here as an operationalization, not a design
term); expected team points per the §1 formula; the simple
baseline's team points with league-mean tempo ("no tempo
interaction"); the naive team-mean over strictly-prior seasons'
verified fixtures with the league-mean fallback (the design names
the baseline without a formula; this operationalization is
recorded, not hidden); team-points MAE per team-game; the paired
season-block bootstrap (10,000 resamples, seed 20261028 — the
parent screen's constants); the leg's pass rule (CI upper bound
< 0 vs both baselines). The full scoring path (three-way fixture
universe, Illinois-first exclusion, walk-forward scoring for
2015-16 → 2022-23 with 2014-15 as the fitting window) is
implemented in the runner behind the premise gate and is
exercised by the family tests on synthetic data — it has never
run on the pinned archive, and on the current archive it must
not. Family tests: **19 passed** (`tests/test_cbb_team_totals.py`);
the repo's CBB test surface passes with them (111 passed); ruff
gate (E9,F821,F822,F823,F811) clean; stdlib only, no dependencies
added.

## 4. First-half lines — NOT_EXECUTABLE

Team-totals design §2:

> "**Named prerequisite (outstanding):** hoopR play-by-play
> release assets (`load_mbb_pbp` family) pinned by the full-tuple
> rule of draft PR #2835 **with schema verification** … Until a
> PBP manifest with a verified schema lands, the half share cannot
> be fitted and **1H is not screenable**. No share is borrowed from
> the NBA fit, from a rule of thumb, or from halving final scores."

Repo state, verified for this report: no manifest on main pins
any play-by-play asset (scan of `research/**/*manifest*.json`
samples — the runner performs and records this scan); the only
occurrence of `load_mbb_pbp` on main is the design document naming
it as outstanding. PR #2835 pinned schedules and player box, no
PBP asset; PRs #2867/#2871 pinned schedules and CBR logs, no PBP.
**Gap, exactly: a successor manifest pinning hoopR `load_mbb_pbp`
release assets by the full-tuple rule with a verified schema.**
Until it lands there is no 1H construction to build and no screen
to run; this packet builds none and invents no share.

## 5. Governed unblocks (either family)

1. A **design amendment** declaring the input convention for the
   Torvik archive (e.g. an explicitly declared prior-day or
   end-of-day convention), with its own review — the route PR
   #2832 admission rule 4 provides — after which this screen runs
   exactly as built here; or
2. An **admitted genuinely morning-of source** (the live-season
   Torvik route of PR #2841 is morning-of by construction for
   2026-27, but the design screen's seasons end at 2022-23; a
   historical morning-of source would need its own admission).

For 1H, the unblock is the §2 prerequisite manifest above, after
which the §2 screen shape (share fitted on strictly prior seasons;
1H-total and 1H-margin MAE vs a naive half-share climatology) can
be built as designed.

Nothing in this packet freezes terms, starts a clock, counts a
game, or changes any family's recorded state.
