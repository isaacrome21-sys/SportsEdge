# DESIGN — NBA Game Props V1

**Status: DESIGN ONLY — NO CONSTRUCTION EXISTS — NO SCREEN RUN — NO CLOCK.**
Date: 2026-10-28. Family state entering this design: game props were
inside the gap plan's NO_CONSTRUCTION tail (never separately inventoried);
this document gives the family a named shape for the first time.

## 1. Scope — game-level props, and what is excluded

In scope: DraftKings game props whose subject is the **game or a team**,
not a player — e.g. highest-scoring quarter / half, race to X points,
first team to score, both-teams-to-score-X ladders, game to reach
overtime, winning-margin bands.

Excluded, expressly: all player props (out of this packet entirely;
the V2 family is quarantined and the Oct 20 secondary player-prop build
is not a foundation here); period totals (governed by
`NBA_PERIOD_LINES_PREREG_DRAFT.md` in this directory); anything whose
subject is a single player's stat line, however DK labels the menu.

## 2. Phasing by what the machinery can honestly support

**Phase A — period-path props (spec'd here).** Highest-scoring quarter
and highest-scoring half are readouts of the *joint period score
distribution* of the two teams. The period engine
(`NBA_TEAM_PERIOD_RATINGS_V1`) emits sanctioned period **point
forecasts** and — by its own build report — "no distributional
conversion is part of this construction, and none is invented here."
Phase A therefore begins with a named, new piece of construction work,
not an assumption:

> **Distributional extension (to be built + separately reviewed):**
> convert the candidate's period point forecasts into period score
> distributions — per team-period, a count distribution centred on the
> forecast with dispersion fitted from strictly-prior period outcomes
> (the same admitted quarter-score feed the period preregistration
> requires), combined across teams and periods with the fitted share
> structure preserved. The extension is a new construction: it gets its
> own design review and its own calibration screen (Brier / log loss of
> the argmax-quarter distribution vs the fitted-shares-only baseline)
> before it may feed any test.

**Phase B — intra-period and event props (named, not spec'd as
buildable today).** Race to X and first team to score live *inside*
quarters; the period fit is at period granularity. A within-period
scoring-process extension (e.g. a possession/Poisson process
interpolated between period checkpoints) plus tip-off / first-possession
data from play-by-play would be required. First-basket *team* props
additionally need authenticated first-possession records. Both are
recorded as NO_CONSTRUCTION with named requirements — not designed
around, not silently dropped.

**Deferred — full-game distribution props.** Overtime probability and
winning-margin bands are functions of the full-game final distribution,
which belongs to the NBA sides/totals successor construction (PR
#2786), itself blocked on a timestamp-authenticated baseline. These
subfamilies are DEFERRED to that family's state. This design does not
route around the block by rebuilding a game distribution here.

## 3. Market baseline and validation shape (for when Phase A exists)

No historical game-prop closing lines exist in any admitted source
(prop-line history is the program-wide Gap G1); the market baseline is
therefore **forward DraftKings capture only**, under the standing
T-1H + FINAL cadence with the game-prop sections recorded per game and
`NOT_OFFERED` stated where DK does not post them. A future
preregistration for Phase A would test: probability quality (Brier /
log loss of model probabilities vs DK offered implied probabilities,
with DK's hold disclosed, never no-vigged silently), calibration by
probability band, and ROI at captured prices — one verdict at a
predeclared minimum sample, anti-peeking, in the house form.

## 4. Activation state and blockers

State reached: **DESIGN**, with Phase A reduced to one named
construction task (the distributional extension). Blockers:

- The distributional extension does not exist; the period engine emits
  point forecasts only.
- Game-prop outcome/line history is NO_DATA (Gap G1) — forward capture
  is the only baseline, so no screen can run before an archive accrues.
