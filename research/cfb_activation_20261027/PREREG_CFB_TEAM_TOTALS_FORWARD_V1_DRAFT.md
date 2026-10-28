# PREREGISTRATION DRAFT — CFB Team Totals Forward Test V1

# DRAFT — NOT FROZEN. NO CLOCK RUNS UNDER THIS DOCUMENT.

**This draft freezes nothing. The historical screen in §4 may be built
and run against it; the forward test in §§5–11 takes effect only if
(1) the screen returns SCREEN_PASS under its fixed criteria and
(2) the owner records a separate prospective freeze of a reviewed
revision of this document, naming the first counted slate. Until both
happen, the family state is DESIGN ONLY and counted rows are zero by
construction.**

- Status: `DRAFT_PREREGISTERED_UNEVALUATED` (screen criteria fixed by
  this draft; forward terms proposed, unfrozen)
- Date drafted: 2026-10-27
- Family in scope: CFB team total points (`TEAM_TOTAL`), one team's
  full-game points including OT per DraftKings settlement, two-sided
  OVER/UNDER at one line. Family registration today:
  NOT in `CFB_RESEARCH_REGISTERED_FAMILIES`; BLOCKED at
  `sportsedge/registry_gate.py`. This draft does not change that.
- Engine under test: `CFB_TEAM_TOTAL_POSSESSION_V1`, specified in
  `DESIGN_CFB_TEAM_TOTALS_V1.md` beside this file (possession model:
  projected drives × projected points per drive; Negative Binomial
  team-points distribution; **no market input to the forecast
  function**).
- Structural model: NBA Team Totals Forward V1 prereg
  (`research/nba_team_totals_forward_20261022/PREREG_NBA_TEAM_TOTALS_FORWARD_V1_DRAFT.md`),
  adapted to CFB data and cadence. Where a number is inherited from
  that document (pick threshold, close-validity windows, gate sizes),
  it is inherited unchanged and says so — no threshold is re-derived
  or shopped for this family.
- Out of scope: game spread / moneyline / game total (retired and
  G3-gated families — nothing here evaluates them), period team
  totals (period-lines design, this pack), player props, SGP, live.

## 0. Up-front risks, stated before any data is seen under this document

1. **The market baseline is a split, not a quote (historical leg).**
   No free historical source carries explicit CFB team-total lines.
   The §4 screen therefore faces the **close-implied team total**
   (closing game total split by the closing spread). That is the
   market's own arithmetic, and it is a real baseline — but it is not
   a book's team-total quote, and a screen pass does not prove the
   construction beats DK's explicit team-total pricing. That proof
   exists only in the forward test, whose baseline is DK's explicit
   captured close. The two legs are never conflated in reporting.
2. **Unmodeled QB factor.** Point-in-time starting-QB designations do
   not exist in any admitted source (Gap G3, under audit elsewhere).
   QB changes move team scoring. The screen measures the exposure
   (§4.4) instead of hiding it; the forward test carries the same
   flag as a reported stratum. If the G3 audit later admits a PIT QB
   input, using it is a **new version** of the construction, never a
   silent amendment.
3. **Shared-data risk.** The screen's seasons (2023–2025) were seen by
   the retired sides/totals constructions. They are DESIGN data for
   this family too: a screen pass is design evidence, and verification
   under the owner's Oct 27, 2026 ruling accrues only from the forward
   test against the existing model and the contemporaneous DK market.

## 1. Question

On identical games: (screen) is the construction's team-points mean
more accurate than the close-implied team total and the naive
baselines, with positive residual beta, on 2023–2025 design seasons?
(forward, if frozen) is it more accurate than DraftKings' closing
explicit team-total line and the incumbent model's implied split, and
do its picked rows earn positive CLV against our own DK captures?

## 2. Market

Exactly one family: CFB `TEAM_TOTAL`. Every other market reaching an
evaluator built under this document is refused `MARKET_OUT_OF_SCOPE`
and excluded from every denominator. A game involving an Illinois
college team (either side) is refused `ILLINOIS_COLLEGE_EXCLUDED`
before pricing, per `sportsedge/registry_gate.py`
(`artifacts.free_models.IL_COLLEGE_NAMES`); excluded games appear in
no denominator and are counted in an exclusion report.

## 3. Data

**Screen data (historical).** SDV `espn_cfb_betting` and
`cfb_schedules` release assets for 2023–2025, read as published (the
converged screen's source; re-pinned by sha256 at screen build), plus
cfbfastR play-by-play releases for feature construction (training
folds may reach back to 2021; evaluation seasons are 2023–2025 only).
CFBD betting lines 2013+ as a cross-check extract for close identity.
All closes are untimestamped snapshots → DESIGN baseline only.

**Forward data (if frozen).** Only the capture program's committed
records: sport, league, event/teams/start CT, market, team, line,
side, American price, book=DraftKings, `captured_at` with zone,
ENTRY/CLOSE designation, source view, entered_by. No fabricated,
retroactive, or backfilled prices. **Arming precondition:** the lines
lane's CFB issue grammar must carry explicit TeamTotal lines (both
teams, both sides) under the standing T-1H / FINAL write cadence
before the first counted slate; until a capture proves that out, no
slate counts.

**Settlement source.** Final team points (including OT) from the SDV
`cfb_schedules` release, joined on game_id. A game with no final at
review is `RESULT_UNAVAILABLE`: excluded and counted, never filled.

**Void and push.** Postponed, suspended-and-not-completed, or
cancelled games are **void** (all rows excluded, counted in a VOID
report). A final equal to a row's line is a **push**: excluded from
the hit-rate leg, counted and reported; accuracy arms unaffected.

**Full slate (forward).** A slate is full when both its ENTRY and
CLOSE capture jobs ran for that game date and every game on the date's
DK board was captured (games with no DK team-total offer count as
captured and go to the missing-offer report). A partial slate's valid
rows still count toward row/game gates.

**Missing-offer games (forward).** Listed per slate in a
`MISSING_OFFER` report with capture id and timestamp. Never backfilled
from another book, a later capture, a derived game-total split, or any
estimate; never in any denominator.

## 4. Historical screen (fixed criteria; one run; no sweeps)

### 4.1 Cohort

FBS vs FBS only; Week 5+ of each season; ≥3 qualifying prior games per
team; expanding-window discipline — features for a game use only games
before its week, and every fitted constant (including the §2.3 pooling
constant's fitted companions and the NB dispersion) is fit only on
seasons strictly before the evaluation season. Illinois-college games
excluded per §2. Identical-rows discipline: every arm is scored on
exactly the same team-game rows.

### 4.2 Arms

- **M:** the construction's mean (and distribution).
- **B-MKT:** close-implied team total (§0.1 identity; sign convention
  proven from the collector code on sampled rows at pin time).
- **B1:** team's walk-forward season-to-date mean points.
- **B2:** walk-forward FBS league mean points per team-game.

### 4.3 Pass criteria (conjunctive; fixed here, before the run)

1. Pooled residual beta ≥ **+0.10**, where beta is the pooled OLS slope
   with intercept of `(actual − B-MKT)` on `(M − B-MKT)` over both
   team rows of every game (the converged screen's preregistered
   statistic, carried to this family unchanged).
2. Beta > 0 in at least **2 of 3** evaluation seasons.
3. Pooled MAE(M) ≤ MAE(B-MKT) **+ 0.5** points on identical rows (the
   converged screen's accuracy tolerance, inherited unchanged despite
   the smaller team-score scale — deliberately conservative), **and**
   MAE(M) < MAE(B1) and MAE(M) < MAE(B2) (point estimates).
4. At least **100 games per evaluation season** in the cohort.
5. Calibration: pooled empirical coverage of M's 80% prediction
   intervals within **[0.72, 0.88]** (design addition for a
   distributional construction; stated here, before the run).

### 4.4 Required reporting (pass or fail)

Per-season and pooled: n, beta, MAEs for all arms, interval coverage;
the **QB-sensitivity stratum** — rows where the post-hoc recorded
starter (CFBD player game stats) differs from the team's prior game —
reported with its own beta/MAE, never used as a feature and never
used to trim the cohort; the Illinois-exclusion count; the full
exclusion accounting table in the converged screen's format.

### 4.5 Verdicts

- `SCREEN_PASS` — all of §4.3 holds. Effect: the construction earns
  the right to **request** an owner freeze of the forward test
  (§§5–11). Nothing else.
- `SCREEN_FAIL` — any leg fails. Effect: the construction is recorded
  FAILED_SCREEN and retired. No constant, threshold, feature, or
  cohort change may be re-run against these seasons under this
  document; a successor is a new construction under a new document.

## 5. Forward test — slates and gates (proposed terms; bind only on freeze)

- Counting starts at zero with the first slate priced after the
  freeze **and** after the forward evaluator is pinned and
  independently reviewed, mirroring the NBA team-totals freeze
  pattern.
- Gates are **minimums**: ≥4 full slates AND ≥150 engine-priced rows
  with valid CLV pairing AND ≥40 distinct games AND ≥50 picked rows.
  ("40 distinct games" is a minimum verdict-review gate, not a cap —
  owner clarification of Oct 22, 2026.)
- **The verdict review happens once, at the first slate close where
  all gates are met. The rows graded at that point are the sample of
  record, and no review is rerun at a later count unless a new
  version preregisters it.** Rows beyond the minimums are included;
  nothing is trimmed to hit a number.
- No interim looks at the primary metrics before that point.
  Operational monitoring (capture counts, refusal counts,
  missing-offer counts) is allowed and reports no accuracy or CLV
  figures.

## 6. Forward test — row rules (proposed)

- Entry: the **first DK capture designated ENTRY** for the game, at
  the **main team-total line** for that team. Later ENTRY captures
  and alternate lines never replace or add rows.
- Side OVER/UNDER; numeric line; finite American price; both sides
  of the entry pair captured (else an entry refusal, §8 pattern).
- Engine stamp required (`engine_id = CFB_TEAM_TOTAL_POSSESSION_V1`,
  `status = PRICED`, priors recorded). Rows without provenance are
  excluded and reported.
- **Pick rule (proposed):** `gap = mean − entry_line`. PICKED OVER
  if `gap ≥ +2.0`, PICKED UNDER if `gap ≤ −2.0`, else PASSED (the
  NBA team-totals threshold, inherited unchanged). One row per team
  per game. Changing it after a freeze is a new version.

## 7. Forward test — primary test (proposed; all four legs required)

Row set: all legs use the same engine-priced rows. A row whose close
fails validity (§8) is excluded from 7a–7d and counts toward the
insufficient-close limit: >20% of engine-priced rows without a valid
close → `INSUFFICIENT_CLOSE_DATA`.

- **7a. Accuracy vs the market (governing).** `ΔMAE_mkt =
  MAE(engine mean) − MAE(DK close line)` paired per row. Required:
  upper bound of the §10 interval for `ΔMAE_mkt` below 0. RMSE
  difference reported alongside.
- **7b. Accuracy vs the other baselines.** Same rows, same interval:
  the engine must beat B1 and B2 (§4.2) **and** the incumbent game
  model's implied split from its captured per-slate emissions
  (pinned by hash in the slate run record).
- **7c. CLV.** Every row scored on side `sign(gap)` (gap = 0 rows
  excluded, counted). Required: mean CLV on PICKED rows > 0 with the
  §10 lower bound above 0, AND picked mean CLV > mean CLV of PASSED
  rows scored on their `sign(gap)` side. CLV computed only on rows
  whose valid close is at the entry line. Moved rows reported
  separately with the one-sided exact sign test of favorable vs
  adverse movement (NFL props v1.1 pattern).
- **7d. Hit rate vs the market.** Only PICKED rows whose valid close
  is at the entry line, graded at the entry line: `hit − p_close`
  with `p_close` the vig-free close probability of the picked side
  (pushes removed for whole-number lines; pushes excluded and
  counted). Required: mean > 0 with the §10 game-clustered,
  Bonferroni-adjusted lower bound > 0.

**Moved-row rules (checked first, in order):** (1) if the one-sided
exact sign test of adverse vs favorable moved PICKED rows gives
p < α/k in the adverse direction → `DOES_NOT_BEAT_MARKET` regardless
of 7a–7d; (2) else if >50% of PICKED rows are moved →
`INSUFFICIENT_CLOSE_DATA`. Zero moved picked rows → rule 1 not run.

Only if neither applies: `BEATS_MARKET` requires **7a AND 7b AND 7c
AND 7d**. A `BEATS_MARKET` verdict is the family's validation evidence
under the owner's Oct 27, 2026 definition; it does not by itself
change registration, eligibility, or promotability — any change is an
owner ruling.

## 8. Forward test — CLV and close validity (proposed)

Inherited unchanged from the NBA team-totals prereg: CLV = no-vig
implied probability at close minus at entry, from real matched
two-sided pairs at the same line. Close = last capture before
kickoff and no more than 60:00 before (exactly 60:00 valid; at/after
kickoff is not a close). Close pair sides within a ≤150-second span.
Entry pair span limit and the 180-second quote-freshness refusal are
adopted at evaluator pin time from the pinned runner's behavior and
recorded in the freeze record. Validity checks run before any moved
classification; a row with no valid close is a capture failure, never
a moved row. "Final" means final among records committed at review
time.

Refusal / exclusion codes follow the NBA team-totals taxonomy
(`NO_CLOSE_ROW`, `LINE_MOVED`, `CLOSE_SINGLE_SIDED`, `CLOSE_NOT_PRETIP`,
`CLOSE_STALE`, `PAIR_SPAN_EXCEEDED`, `QUOTE_STALE_180S`;
`RESULT_UNAVAILABLE`, `VOID`, `PUSH`, `GAP_ZERO`;
`ILLINOIS_COLLEGE_EXCLUDED`, `MARKET_OUT_OF_SCOPE`,
`ENGINE_PROVENANCE_MISSING`, …), with the full CFB list fixed in the
evaluator at pin time. Any code appearing at review that the frozen
document does not list is itself a defect and blocks the verdict
(`UNDECLARED_REFUSAL_CODE`).

## 9. (Reserved — refusal-code full list lands with the evaluator pin.)

## 10. Multiple testing and intervals (proposed)

All intervals: **game-cluster bootstrap, 10,000 resamples**, seed
fixed and recorded at freeze, two-sided at level **1 − α/k**,
α = 0.05. **k** = the number of forward clocks whose counting windows
overlap this test's window, counting this test from its freeze date;
the clock-ID list is recorded at freeze and again at review; the
larger k is used.

## 11. Version rules (proposed)

Engine, runner, history-store pins, pick rule, and evaluator are
fixed by sha256 at any future freeze commit; each slate's run record
must prove it executed the frozen hashes or the slate does not count.
Any change after a freeze is a new version under a new document,
scored only from its own freeze forward. Frozen text is never edited;
amendments supersede by reference. Each slate's history snapshot
includes only games final before the entry capture, its hash recorded
before pricing; a failed refresh fails the slate closed.

## 12. Path from this draft (checklist)

- [ ] Independent review of this draft by a checker who did not draft
      it.
- [ ] Screen built to §4 (hash-pinned inputs), run once, verdict and
      full §4.4 reporting committed.
- [ ] If SCREEN_FAIL: stop. Construction retired; this checklist
      closes.
- [ ] If SCREEN_PASS: lane TeamTotal capture proven on real slates
      (arming precondition, §3).
- [ ] Forward evaluator built, hash-pinned to the frozen revision,
      independently reviewed.
- [ ] Owner freeze recorded prospectively, naming the first counted
      slate. **Not requested by this draft.**
