# NHL_ATTEMPT2_V1 — preregistration terms record + freeze-completeness audit

**Status: PACKAGE RECORD — DRAFT. This document transcribes the
merged design's Stage B terms and audits them; it amends nothing.**
The design of record is
`research/activation_designs_20261027/NHL_SIDES_TOTALS_DESIGN.md`
(PR #2839, sha256 in `SPEC_HASHES.txt`). Where the design is quoted,
the quote governs; where this record proposes a completion, the
proposal is labeled **DRAFT COMPLETION PROPOSAL — OWNER ADOPTION
REQUIRED** and has no force until a design amendment carrying it is
adopted by the owner under independent review and merged.

## 1. The terms the design DOES fix (transcribed)

Stage B is a one-look forward market validation, not a season-long
counted clock. The design fixes, in advance:

- **Precondition:** Stage A verdict = PASS on Nov 30, 2026, and NHL
  capture flowing under the restart pack.
- **Window:** Dec 1, 2026 – Jan 31, 2027 regular-season games with
  paired DK captures (ML, puck line, total from the FINAL write).
- **Candidate:** attempt-2 v1 as specified in the design, fitted only
  on games before Dec 1, 2026 (MoneyPuck design fit) and updated
  strictly forward.
- **Comparators, on identical games:** (a) the public boxscore
  baseline's probabilities (`sportsedge/sports/nhl/public_baseline.py`,
  the existing-model leg); (b) DK closing no-vig probabilities (the
  market leg).
- **Primary metrics:** log loss on moneyline; log loss on the total
  (distribution evaluated at the offered line).
- **PASS:** candidate beats BOTH comparators on moneyline log loss
  AND does not lose to either on totals log loss, paired one-sided
  significance at alpha = 0.05 / k, moneyline calibration slope within
  [0.8, 1.25]. **One look, Feb 1, 2027.**
- **Puck line:** scored and reported, not gated.
- **CLV/ROI:** graded and reported; not gates.
- **Construction form:** strictly-prior exponentially weighted team
  xG rates (half-life fixed at freeze) shrunk toward league rates by
  games played; goaltender adjustment from the confirmed starter's
  strictly-prior save performance vs shot quality faced (unconfirmed
  starter = weighted starter/backup blend, row flagged degraded);
  regulation-first simulation (Poisson with a dispersion parameter
  fit on design data) with OT/SO mass added once from the regulation
  tie probability; all outputs from the one simulation.
- **Data law:** MoneyPuck is the admitted input (PR #2859, attempt-2
  only, no cross-vintage pooling; declared treatment
  `SINGLE_VINTAGE_ONLY:rebuilt_2026_27`); no historical NHL closing
  archive is claimed; verification accrues forward only.

That is a real protocol: window, comparators, metrics, PASS shape,
and look discipline are all fixed. The audit below is about what a
**freeze** additionally needs — the terms that make the frozen object
complete enough that the Feb 1, 2027 look is a computation, not a
negotiation.

## 2. The audit — findings

### G-1 — No pick rule: the design's promised ROI is undefined

The design's PASS test is probability-only (log loss over all paired
games) and needs no picks; it is fully defined as written. But the
same protocol promises "CLV/ROI graded and reported," and neither
term is computable as drafted: ROI requires a set of staked rows and
a designated side per row, and program CLV is graded on selected
rows. The design names no selection rule — no edge threshold, no
designated-side rule, no statement of which markets' rows enter the
report. (Contrast the frozen siblings: NFL team totals' prereg §5
fixes its pick thresholds; CBB's gap of the same shape was cured by
Amendment 2's per-market thresholds.) A freeze that leaves ROI
undefined invites the reporting rule to be chosen after the window's
results are visible — the exact failure the pick-rule requirement
exists to prevent.

**DRAFT COMPLETION PROPOSAL — OWNER ADOPTION REQUIRED.** A design
amendment fixes, per market (moneyline, total; puck line if its
report is to carry ROI): the designated side (the side whose model
probability exceeds its entry no-vig probability by the larger
margin), a minimum edge threshold in probability points, the entry
(the T-1H write's no-vig price), and the ROI/CLV row set (picked rows
with a valid close under the G-3 rule). **The form transfers from
CBB Amendment 2 §1; the calibration route does not** — CBB's values
were derived as ≈0.2σ̂ from its design screens' pooled MAEs, and this
family has no historical screen and no MAE to derive from (the
admission bars inventing one). The amendment must fix the threshold
values on grounds it states itself; this package proposes none.

### G-2 — The paired-significance construction is unspecified

PASS turns on "paired one-sided significance at alpha = 0.05 / k,"
and on a "moneyline calibration slope within [0.8, 1.25]." Neither is
a computation as written: no resampling unit (game? team-week?),
method, resample count, or seed is named for the paired test, and the
calibration slope's estimator is unnamed (logistic recalibration
slope on the moneyline probabilities is the program's usual reading,
but the design does not say it, nor what it is fit on). Two honest
implementations of the same sentence can reach opposite verdicts on
the same window — this is CBB gap G-2 in this family's dress.

**DRAFT COMPLETION PROPOSAL — OWNER ADOPTION REQUIRED.** Adopt the
frozen sibling construction (NFL team-totals prereg §9, carried into
CBB Amendment 2 §2): game-cluster bootstrap over games, 10,000
resamples, seed 20261028, intervals at 1 − α/k with k recomputed at
the verdict (larger of freeze-time and verdict-time counts governs);
per-game paired log-loss differences as the resampled quantity, for
both gated legs. The amendment also names the calibration-slope
estimator expressly (form, inputs, and the row set it is fit on).

### G-3 — No close-validity rule (and no entry rule for CLV)

Stage B's market leg is "DK closing no-vig probabilities" from
captures taken "(…from the FINAL write)." The design fixes no
validity terms for that close: no bound on how stale a FINAL write
may be, no disposition for a game whose FINAL write is missing,
one-sided, or lands after puck drop, no missing-close share at which
the market leg becomes insufficient, and — for the G-1 report — no
entry-side rule (the standing cadence's T-1H write is the program's
entry everywhere else, but this design does not say so). The lane's
Oct 28, 2026 delivery audit (38 due marks, 0 delivered on the night)
is the standing proof that missing and late closes are not edge
cases; a protocol silent on them will meet them in its window.

**DRAFT COMPLETION PROPOSAL — OWNER ADOPTION REQUIRED.** Adopt the
close-validity form the program has converged on (NFL v1.1 close
rule; CBB Amendment 2 §3): the close is the FINAL write; a close is
valid only if its capture precedes puck drop by no more than a fixed
bound (CBB's form: ≤ 60:00 before tip, exactly 60:00 valid; a capture
at or after start is not a close), both sides present; rows failing
validity are capture failures under named codes; and an
insufficient-close-data trip — if the share of paired games without
a valid close exceeds 20%, the market leg's verdict is labeled
insufficient rather than passed or failed on a thinned set. The
amendment states the entry rule for CLV in the same section (the
T-1H write, per standing cadence, unless it says otherwise).

### G-4 — No minimum universe and no insufficient-data disposition

The sibling team-totals protocol fixes a minimum universe (200
team-games per side) in advance. This design fixes none for sides/
totals: no minimum paired-game count for the moneyline or totals
legs, and no stated disposition if the window's paired universe is
thin. Under the one-look law the window cannot be extended and no
second look exists, so an unmet floor discovered on Feb 1, 2027 has
no lawful remedy unless the disposition is fixed now.

**DRAFT COMPLETION PROPOSAL — OWNER ADOPTION REQUIRED.** The
amendment fixes a minimum paired-game count per gated leg and the
disposition if it is unmet at the one look: the leg's verdict is
recorded INSUFFICIENT_DATA (neither PASS nor FAIL), the construction
is neither validated nor retired on that leg, and any further window
requires a new preregistration. The counts themselves are the
amendment's to fix; the capture reality of the Dec 1 – Jan 31 slate
(≈ two months of NHL games, lane delivery permitting) is the input
it should reason from.

### F-1 — No forward runner exists

The build (PR #2877) delivered the construction library
(`sportsedge/nhl_attempt2.py`: rates, goalie adjustment, simulation,
`price_game` on in-memory rows under an explicit `Params`, every
output stamped counted=False / frozen=False /
validation_credit=False) and a machinery-proof landing check on a
historical slate. That is not a forward runner. Nothing on main:
consumes forward lane captures into priced slate records for this
family; produces the Stage B fit artifact (the frozen-constants fit
on games before Dec 1, 2026 — `fit_constants.py` is a build-stage
dispersion fit on the Oct 28 pull, not that artifact); or evaluates
the Feb 1 look (comparator legs, paired test, calibration slope)
under a counted entry point. The frozen-constants pricing path
refuses `NHL_ATTEMPT2_NOT_FROZEN` while the freeze-owed constants
are None — correct behavior that also proves the point: today there
is no runnable forward path to freeze. (Same shape as CBB finding
F-1; the CBB act's remedy is the model.)

**Act prerequisite (not an amendment gap):** a forward runner build
implementing the design + the adopted amendment, with a NON_COUNTED
landing check reproducing the construction's outputs on a historical
date (construction equivalence) and a demonstrated capture → price →
record path on a current non-counted slate, before the first window
game. The freeze act re-pins `model_version` to the built runner.

### G-5 — Freeze-owed constants are still unpinned

The design defers these values to the freeze expressly, so their
absence is not a design defect — but the act cannot execute until
each is pinned on the act's head, and one carries a methodological
choice the act must record:

- `HALF_LIFE_GAMES` — None (design §1: "half-life fixed at freeze").
- `SHRINKAGE_PRIOR_GAMES` — None.
- `GOALIE_SHRINKAGE_GAMES` — None (build-freeze-owed, constants file).
- `DISPERSION_PHI` — build-stage fit = 1.0 (pure Poisson): the
  declared method-of-moments estimate on the pinned design set was
  0.8208, below the Poisson floor, and the build record states the
  limitation — game-level xG as the mean proxy understates the
  dispersion a rate-based mean leaves in residuals — and names the
  alternative reading (a residuals-around-strictly-prior-rates fit).
  The constants file states "the freeze fit governs." The act must
  run the freeze fit on the exact frozen head, adjudicate the two
  readings on the record, and pin the result; carrying the build's
  floored 1.0 forward by default is not a fit.
- `OT_HOME_WIN_SHARE` / `OT_DECISION_SHARE` — 0.5 placeholders,
  NOT FITTED; decision D-2 in `DECISIONS_AND_READINGS.md`.

## 3. What is NOT a gap

- **MoneyPuck admission** — the design's named blocker is closed:
  admission landed as PR #2859, scoped to attempt-2 input, with the
  vintage law the construction already enforces in tests.
- **The existing-model comparator exists** — the public boxscore
  baseline is on main and is the design's named comparator (a); it
  is a development baseline, explicitly non-xG, and the design does
  not relabel it.
- **No historical screen is missing** — the design specifies none,
  deliberately, and the admission's forward-only law bars presenting
  one as validation. This package invents none.
- **Stage A is not this family's to complete** — it is locked under
  its own pre-lock and act; this package only records that its
  verdict gates Stage B.
