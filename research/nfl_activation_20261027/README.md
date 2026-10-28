# NFL ACTIVATION PACK — team totals, period lines, game props, SGP, live

**Prepared Oct 27–28, 2026, under the owner's directive that every family
reach clock-running, armed, or screening — no family sits at
NO_CONSTRUCTION.** This pack carries the five remaining NFL families out
of NO_CONSTRUCTION with a construction design and a preregistration draft
each (the live family: a capture pilot spec — no construction until
capture exists). **Nothing in this pack freezes anything, starts a
clock, prices a live game, or claims a validation.** Freezing is the
owner's act, per family. All work is PAPER / research only.

## Standing law this pack obeys

- **VERIFIED** (owner ruling, Oct 27, 2026 ~22:53 CT, repealing the
  50-graded-picks gate): a construction that has passed its
  preregistered chronological out-of-sample validation against BOTH the
  existing model (Lane A) and a contemporaneous market baseline.
  Forward clocks keep grading but no longer gate the label. Nothing in
  this pack has passed anything; no document here uses the word as a
  claim about its own family.
- FAILED constructions stay retired; replacements are new constructions.
  Two retired constructions are directly relevant and are **not**
  resurrected: the declared-fraction quarter totals / quarter team
  totals (`sportsedge/market_coverage.py`, failed their harness vs
  naive) and NFL_ANCHORED_RATINGS_V1 (sides/totals).
- Historical data seen by failed constructions is DESIGN data.
  Historical screens are entry tickets, never validation. Every screen
  in this pack ran on seen seasons and says so.
- Prop-family verification is forward-capture only (gap G1: no
  historical prop closes exist). NFL game-line closes exist only as
  nflverse's single untimestamped snapshot per game (gap G7): usable as
  a design diagnostic, never as verified CLV and never as a validation
  baseline.
- Multiple testing: every validation in this pack computes intervals at
  level 1 − α/k, α = 0.05, k = the number of families validated or
  under active forward test in the program at verdict time (recorded in
  each verdict record; the larger k governs where two counts exist).
- Inputs are free and public only (owner's free-only data law,
  Oct 27, 2026): nflverse releases and the program's own timestamped
  DraftKings captures. No paid source is named as a dependency anywhere
  in this pack.
- Frozen families are untouched: anytime-TD v1.1, Part 2 / Part 2B
  terms, and the passing-yards v2 screen keep their written terms.
  This pack borrows their *forms* (missing-close rule, YES_ONLY CLV
  form, shrinkage discipline) only where a draft says so explicitly and
  justifies it.

## The five families

| Family | Construction / deliverable | Design screen | Activation state on landing |
|---|---|---|---|
| NFL team totals | `NFL_TEAM_TOTAL_DIST_V1` — opponent-adjusted score distribution (design + prereg draft + framework config) | **PASS** vs naive baselines (see `SCREEN_REPORT.md`); implied-split diagnostic disclosed | **ARMED pending owner freeze** once the engine build lands and is hash-pinned; the prereg draft's freeze checklist names the remaining steps |
| NFL quarters / halves | `NFL_PERIOD_SHARE_V1` — point-in-time period-share means (design + prereg draft + framework config) | **FAILED_SCREEN** — team period shares do not beat league shares (recorded in full, not tuned away) | **DESIGN ONLY** — the failed construction does not advance; named missing steps: capture expansion, intake-grammar extension, a drive-state v2 design |
| NFL game props (TD exotics beyond anytime-TD) | `NFL_FIRST_TD_V1` — two-stage first-scorer model (design + prereg draft + framework config). The 2+ TD market already has its Oct 20 prereg draft (`research/forward_validation_program_20261020/drafts/PREREG_NFL_TWO_PLUS_TD_FORWARD_V1_DRAFT.md`), which this pack does not alter or re-draft | Not run — the attribution panel does not exist yet (the family's NO_DATA blocker of record) | **DESIGN ONLY** — named missing steps: first-scoring attribution panel admission, capture expansion for the first-TD board, calibration screen |
| NFL SGP | `NFL_SGP_JOINT_V1` — single-simulation joint engine over leg families (design + prereg draft + framework config) | Not run — leg engines and the fixed-menu SGP quote capture do not exist yet | **DESIGN ONLY** — hard dependency: SGP rows may only use legs whose families carry committed engines at or beyond prereg-draft state; named missing steps in the design |
| NFL live in-play | Capture pilot spec (no construction, no framework config — declaring one would imply a priced family) | n/a | **DESIGN ONLY (pilot spec)** — the pilot itself is the missing step; construction design is refused until the pilot reports |

## Common validation architecture (all four priced families)

Each prereg draft fixes, in advance: the chronological forward sample
(DK captures from the family's freeze; no backfill; rows priced before
a freeze are historical, never prospective); the two baselines (Lane A
as it stands at freeze, hash-pinned; the contemporaneous DK close under
the Capture Spec V1 readability rule — same event/subject/market/line,
both prices where the board is two-sided, captured before start and no
more than 60 minutes before it); the missing-close taxonomy of the
frozen Part 2 test, adopted verbatim in effect; a single verdict review
at the first slate close where all gates are met (anti-peeking; rows
beyond the minimums are included, never trimmed); and per-market
verdicts, never pooled across markets. Where a family deviates from the
Part 2 / NBA-team-totals templates, its draft says so and justifies the
deviation (e.g. YES_ONLY raw-implied CLV for one-sided boards — the
locked anytime-TD form).

## Dependencies between families

- SGP consumes team totals (this pack), Part 2 / Part 2B props (frozen
  tests running), and game lines. Its freeze is necessarily last.
- Period lines and game props both wait on capture expansions (lane
  work, named in their designs); neither expansion touches the frozen
  families' capture subsets.
- Live waits on nothing in this pack; its pilot is lane infrastructure,
  and 2H lines are assigned to the live scope (they are priced at
  halftime, i.e. in-play), which keeps the period family's markets
  regulation-defined and unambiguous.

## Files

- `DESIGN_NFL_TEAM_TOTALS_V1.md`, `PREREG_NFL_TEAM_TOTALS_FORWARD_V1_DRAFT.md`
- `DESIGN_NFL_PERIOD_LINES_V1.md`, `PREREG_NFL_PERIOD_LINES_FORWARD_V1_DRAFT.md`
- `DESIGN_NFL_GAME_PROPS_TD_V1.md`, `PREREG_NFL_FIRST_TD_FORWARD_V1_DRAFT.md`
- `DESIGN_NFL_SGP_JOINT_V1.md`, `PREREG_NFL_SGP_FORWARD_V1_DRAFT.md`
- `NFL_LIVE_CAPTURE_PILOT_SPEC_V1.md`
- `screen_nfl_activation_v1.py`, `screen_results_v1.json`, `SCREEN_REPORT.md`
- Framework configs (all `DRAFT — NOT FROZEN`): `sportsedge/forward_validation/configs/nfl_team_total.json`, `nfl_period_lines.json`, `nfl_first_td.json`, `nfl_sgp.json`
- `SPEC_HASHES.txt` — sha256 of every document in this pack.
