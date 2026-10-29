# NHL_ATTEMPT2_V1 — adoption-time decisions and readings

**Status: PACKAGE RECORD — DRAFT. This document names decisions; it
makes none of them.** Each decision below is the owner's (by adoption
act, with a design amendment where one is required), taken before or
at the freeze act. Options and consequences are stated from the
record; where the build or design already took a reading, that
reading is listed for confirmation (R-1…R-7) — an uncorrected reading
left ambiguous stops the act (the CBB checklists' rule).

## D-1 — Home-ice: venue-blind as drafted, or a declared home term

**The state of the record.** The attempt-2 design specifies no
home-ice term; build reading 5 records the consequence plainly:
"home-ice belongs to the separate, locked Stage A home-ice v2
model," and the build's landing check prices are venue-blind by
construction — visibly so: all three Oct 26, 2026 road teams priced
slightly ahead. The construction as drafted therefore enters Stage B
with a known, structural home/away mispricing: league home teams
win more often than venue-blind rates imply, and the moneyline log
loss leg grades exactly that.

**Option A — keep the construction venue-blind into Stage B, as
drafted.** No amendment; the freeze pins the construction as built.
Consequences: the design's own allocation stands (home-ice is Stage
A's question, tested separately under its lock); Stage B then tests
whether the xG rates + goalie layer beat the market *despite* the
missing term — a harder test, taken knowingly, and a FAIL on the
moneyline leg would be partly attributable to a term everyone knew
was absent, which weakens the verdict's information about the rest
of the construction. Nothing is hidden: the landing check already
disclosed the symptom.

**Option B — a design amendment adds a declared home term before
the freeze.** Consequences: the construction changes, so the
amendment goes through its own review and lands before the freeze
act (the freeze then pins the amended construction). The term must
be attempt-2's own: **Stage A's fitted home-ice value cannot be
borrowed** — it belongs to a different, locked construction (fit on
2024–25 regulation goals under the pre-lock's terms), and importing
it would contaminate both tests. A lawful source exists inside this
family's own admitted data: MoneyPuck team rows carry home/away
identity, so a home scoring-rate factor (or home win-probability
uplift) can be fit on the same declared design data as the Stage B
fit, strictly prior, inside the single rebuilt vintage. The
amendment must fix the term's form (rate multiplier vs probability
adjustment), its fit, and where it enters the simulation.

**What this package does not do:** choose. The design as merged is
Option A by silence; silence is not a ruling. The freeze act must
record which option the owner took.

## D-2 — OT/SO shares: source them, or declare the neutral constants

**The state of the record.** `OT_HOME_WIN_SHARE` and
`OT_DECISION_SHARE` ship as neutral 0.5 placeholders labeled
NOT FITTED (`sportsedge/nhl_attempt2_constants.py`). The build
establishes they are **not identifiable from the admitted MoneyPuck
surface**: a one-goal final conflates regulation and OT decisions,
and the shootout winner is absent from shot-derived goals. They are
not cosmetic: the home share splits the regulation tie mass in the
moneyline, and the decision share drives the single added goal in
the totals layer — the two gated legs of Stage B both consume them.

**Option A — source them from the NHL API design ground truth the
design names.** The design's Inputs name the official NHL API as
supplying "schedule/results ground truth for design and grading."
Regulation/OT/SO outcomes are result facts, computable from
completed games' records (e.g., the 2026-27 games before Dec 1,
2026, inside the declared fit window's data discipline — results of
games already played are design data for constants, not validation
data). Consequences: the constants become fitted values with a
stated universe and a reproducible computation the act pins. One
role question the act must record expressly: the API's in-repo
admission is as a research/archive collector whose envelopes are
marked `pricing_input: false`; using its results to fit two design
constants is a design/grading use, which the design text supports,
but the freeze record should state that reading rather than let it
pass silently — and if the owner or reviewer reads the role more
narrowly, Option B is the fallback.

**Option B — declare 0.5 / 0.5 as design constants.** No new source,
no fit; the freeze record declares the neutral values as terms of
the construction. Consequences: lawful and honest if declared, but
the totals layer's expected added goal and the moneyline's OT split
are then wrong wherever the true shares differ from neutral, by an
amount nobody has measured — the Stage B test would grade a
construction carrying two constants known to be placeholders. A
declared-placeholder freeze is defensible only as an explicit owner
choice, not as a default the act slides into.

**Not an option:** fitting them from MoneyPuck (refused by the
build's identifiability finding), or leaving the build-stage
placeholders in place without a freeze-record declaration (that is
Option B without the honesty).

## S-1 — Sequencing: freeze before the Stage A verdict, or after

Stage B's fit must run under frozen constants on games before
Dec 1, 2026, and the window opens Dec 1. The Stage A verdict lands
Nov 30, 2026. Two readings:

- **Freeze after PASS.** The act executes in the Nov 30 → Dec 1
  interval. The fit data bound ("games before Dec 1") is a bound on
  data, not on the fit's run date, so a freeze landing Dec 1 before
  the first counted puck drop still fits lawfully — but the whole
  closing sequence (amendment already landed, runner built,
  readiness audit, exact-head review, merge) must be staged in
  advance so only the merge waits on the verdict, and any slip
  compresses the fit against the window's first games. If Stage A
  fails, no freeze exists and nothing needs unwinding.
- **Freeze before the verdict (constants-and-terms act), with
  Stage B expressly conditional on PASS.** The act can execute on a
  calmer calendar and the fit can be prepared; if Stage A fails, the
  freeze becomes a dead record — the construction "returns to
  design" per the design, the frozen config would have to be
  retired by a further act, and no row may ever count under it.
  Nothing in the design's text bars freezing early; the bar it sets
  is on Stage B *running*. But the program's freeze discipline
  treats a freeze as the start of a validation commitment, and a
  knowingly conditional freeze is a new shape the owner should
  adopt expressly, not by implication.

The package takes no side; the act records the owner's ruling. What
is not available under either reading: pricing window games under
unfrozen constants and calling the rows counted later (no backfill),
or re-freezing amended constants mid-window (a mid-window change is
a new version, scored forward from its own freeze).

## R-1…R-7 — Build readings the freeze act confirms or corrects

Taken by the build (PR #2877) where the design is silent; recorded
in `research/nhl_attempt2_build_20261028/BUILD_RECORD.md`. The
freeze record states the outcome for each:

| # | Reading | 
|---|---|
| R-1 | Situation basis 'all' for rate inputs (the admitted collector's strictly-prior aggregate precedent; includes OT-period play in inputs while outputs are regulation distributions). |
| R-2 | Matchup form off × def / league, league rate = mean of the weighted league offensive and defensive rates. |
| R-3 | Half-life clock in team games, not days ("shrunk … by games played"). |
| R-4 | Goaltender adjustment additive (goals-saved-above-xG per game, shrunk toward 0 by games played, subtracted from the opposing mean); unconfirmed blend pools goalies weighted by games played. |
| R-5 | No home-ice term — superseded by decision D-1; the act records D-1's outcome here. |
| R-6 | OT/SO parameters not identifiable from the admitted surface; 0.5 placeholders NOT FITTED — superseded by decision D-2. |
| R-7 | Regular-season window filter: fit/pricing features use gameDate ≥ 20261008 for 2026-27 (admission §4.3 leaves competition windows to the consumer). |

Also carried to the act from the constants file (computational
bounds, build choices, not design terms): goal grid 0..12 with the
tail folded into the last cell; `MIN_MEAN` floor 0.05. The act
confirms them as construction constants or corrects them before the
freeze pins the file.
