# PREREGISTRATION DRAFT — NBA Period Totals Forward Test V1

# DRAFT — NOT FROZEN — NOT IN FORCE — NO GAMES COUNT

**This document is a draft. Freezing is the owner's act. No game, row, or
capture counts toward this test until the owner freezes this document (or
a successor) as the governing preregistration AND the data gates in §4
are met. Nothing here changes any family's registration, eligibility, or
validation state.**

- Status: `DRAFT_NOT_IN_FORCE`
- Date drafted: 2026-10-28
- Families in scope (§2): NBA team quarter totals, game quarter totals,
  team half totals, game half totals — current recorded state
  NO_CONSTRUCTION (gap plan, Oct 27, 2026), with a screened candidate
  construction (§3) and no preregistration until this draft.
- Candidate: `NBA_TEAM_PERIOD_RATINGS_V1`
  (`sportsedge/nba_team_period_engine.py`).

## 1. Honest starting state

The candidate exists and has been *calibration-screened*; it has never
faced a market. The Oct 20, 2026 build screen
(`research/nba_team_period_20261020/REPORT.md`, SBR archive vintage
sha256 `0c985848…`, CALIBRATION ONLY — no market leg exists for these
families) found, with all paired CIs entirely below zero vs both
climatology baselines (214 ISO-week blocks, seed 20261018):

| Subfamily | n | Candidate MAE | Baselines B1 / B2 | Screen provenance |
|---|---|---|---|---|
| TEAM_QUARTER_TOTAL | 62,024 | 4.6103 | 4.7070 / 4.7099 | exact reproduction of sweep B11 |
| GAME_QUARTER_TOTAL | 31,012 | 6.6518 | 6.7483 / 6.8135 | first screen (mechanical aggregation) |
| TEAM_HALF_TOTAL | 31,012 | 6.4541 | 6.6358 / 6.7228 | first screen |
| GAME_HALF_TOTAL | 15,506 | 9.7481 | 9.9512 / 10.1957 | first screen |

A calibration pass is not validation: under the owner's Oct 27, 2026
definition, this family becomes verified only by passing the forward
test drafted here, against both the existing-model baselines and a
contemporaneous market baseline.

## 2. Markets in scope — exactly four

- `TEAM_QUARTER_TOTAL` — one team's points in one quarter, over/under.
- `GAME_QUARTER_TOTAL` — both teams' points in one quarter, over/under.
- `TEAM_HALF_TOTAL` — one team's points in one half, over/under.
- `GAME_HALF_TOTAL` — both teams' points in one half, over/under.

Expressly out of scope: full-game `TEAM_TOTAL` (a separate family, ARMED
under its own preregistration, PR #2504 — not this document's to govern);
period spreads and period moneylines (**NO_CONSTRUCTION** — the shares
construction yields period points only, and no sanctioned period
win-probability construction exists); player period props
(NO_CONSTRUCTION + NO_DATA, and player props are outside this packet
entirely).

## 3. Candidate construction (frozen by reference, not by this draft)

The Oct 18 backtest-everything sweep's B4/B11 calibration constructions,
implemented unchanged as an engine. Spec:
`backtest_everything_20261018/specs/SPEC_NBA_GAME_LEVEL_V1.md`
(sha256 `cc96783f…`). Quarter points for a team = fitted quarter share ×
the team's ratings-predicted game points (`ratings_model.NBARatings`,
committed defaults); shares come from
`sportsedge/sports/nba/period_history.py::fit_period_parameters` under
the frozen fit protocol — span seasons ≤ 2014, day-granularity mapping,
as_of 2015-10-01 UTC — published fit version
`NBA_PERIOD_FIT_V1:310b42f5bc41`. Half and game forms are exact
mechanical sums of the scored primitives, not new models. Sufficiency
gates, fail-closed: ≥ 10 prior in-season games per team and ≥ 200 prior
in-season league team-games, all strictly before the target game.

## 4. Data gates — both must hold before any row can count

1. **Period outcomes feed.** The maintained sportsdataverse assets carry
   NO quarter scores (verified Oct 20, 2026), so on the maintained path
   the engine refuses `NBA_PERIOD_HISTORY_UNAVAILABLE` (and
   `NBA_PERIOD_FIT_HISTORY_MISSING` where the frozen fit span is
   absent). A lawful `NBAPeriodObservation`-form feed (e.g. derived from
   the admitted {nbadatar} play-by-play / quarter-split source) must be
   admitted under its own record before forward grading is possible.
2. **Market captures.** Rows price and grade only from timestamped
   DraftKings captures under the standing lane cadence (T-1H and FINAL
   writes, parser-safe grammar, #2792 five-stage receipts). The capture
   grammar must record the four period sections per game, with
   `NOT_OFFERED` stated explicitly where DK does not post a section —
   never a silently shrunk census.

## 5. Forward test terms (to be frozen verbatim if the owner freezes)

- **Population:** NBA regular-season games on or after the freeze date,
  priced pre-tip from a T-1H capture and graded against the FINAL
  capture's closing period line.
- **Accuracy leg (existing-model baseline):** paired MAE of the
  candidate vs the B1/B2 climatology baselines of the Oct 18 spec,
  recomputed on the same forward games, ISO-week-block bootstrap;
  PASS requires the 95% CI upper bound < 0 against both baselines, per
  subfamily.
- **Market leg (contemporaneous market baseline):** CLV against the
  closing period line > 0 and ROI at captured entry prices > 0, per
  subfamily. Untimestamped or secondary-source lines never grade a row.
- **One verdict, once:** per subfamily, at the first slate close where
  ≥ 40 distinct games have been graded (the standing minimum-gate
  clarification: 40 is a floor, not a cap), both legs are read together
  and the verdict is recorded once. No re-review at a later count
  absent a new preregistration. Subfamilies verdict independently.
- **Failure** of either leg records the subfamily FAILED_SCREEN under
  this version; any retry is a new construction under a new
  preregistration, never a tuned re-run on the same forward rows.

## 6. Activation state and blockers

State reached: **PREREG DRAFTED** on a calibration-screened candidate.
Blockers, one line each:

- Period outcomes are NO_DATA on the maintained data path — an admitted
  quarter-score feed is required before grading (§4.1).
- Freeze is the owner's act; until then this draft counts nothing.
