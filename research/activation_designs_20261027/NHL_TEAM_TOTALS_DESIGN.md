# NHL team totals — construction design + preregistration draft

**Status: DESIGN ONLY — preregistration DRAFT, not frozen. No clock, no
verified claim, no PLAY.** Derivative family of the NHL sides/totals
attempt-2 construction (NHL_SIDES_TOTALS_DESIGN.md): team totals are the
per-team goal distributions of the same simulation, priced against DK's
team-total lines. Today the card reports team totals as
`NO_MODEL:FROZEN_OWNER_MISSING`; this draft is the path out of that state
and creates no model by itself.

## Edge mechanism

DK team totals are typically derived from the game total and the spread —
an implied split. A simulation that carries each team's own rate (xG
offense, opponent xG defense, goaltender state) produces a team-total
distribution that is NOT a split of anything: when the two teams' rates
are asymmetric in ways the game total hides (a strong offense against a
weak goaltender in a game whose total is suppressed by the other matchup),
the implied split and the simulated distribution disagree, and the
simulated one is the candidate edge. The disagreement is testable per game
and is the family's whole thesis; if the sim's splits merely reproduce the
implied splits, there is no family here and the validation will say so.

## Construction

- Per-team regulation goal distributions from the parent construction
  (same fitted rates, same goaltender adjustment), propagated through the
  parent's OT layer for the DK team-total settlement basis; the settlement
  basis (regulation vs incl. OT) is read from DK's posted market rules at
  capture time and recorded per row — never assumed.
- No separate fit. Any team-total-specific recalibration discovered in
  design becomes a new version of THIS family with its own draft, never a
  silent tweak of the parent.

## Inputs

Identical to the parent's (MoneyPuck xG foundation pending admission;
official API ground truth; forward DK captures). Team-total lines come
from the DK event page in the game's T-1H/FINAL writes; where the parser
cannot read them as priced lines they ride in the line-3 comment verbatim
(the standing grammar's rule for unreadable markets) and are transcribed
into the family's dataset with the capture's event ID and timestamp.

## Validation protocol (fixed in advance; one look)

Runs inside the parent's Stage B window (Dec 1, 2026 – Jan 31, 2027) on
games with paired DK team-total captures; minimum 200 team-games per side
(home/away pooled with a side indicator, fixed here). Comparators:
(a) the implied-split distribution — game-total distribution split by the
closing moneyline-implied share, i.e. the "existing model" for this
family is the market's own derivation, made explicit; (b) DK team-total
no-vig probabilities at the offered lines. Primary metric: log loss on
the team-total over/under outcome at the offered line. PASS = candidate
beats BOTH at alpha = 0.05 / k, one look with the parent's Feb 1, 2027
verdict. This family's verdict is independent of the parent's: the parent
can pass on moneyline while team totals fail, and vice versa — each is
reported as its own row, because a split-level error can hide inside a
correct game total.

## Activation state on landing

DESIGN ONLY; activates on the parent's schedule. If the parent's Stage A
fails, this family's window does not open (the rates it prices from are
the parent's construction).

## Blockers

- Parent construction (design #4) and its blockers (MoneyPuck admission,
  rate artifact, capture restart).
- DK team-total presence/depth on NHL event pages must be confirmed in
  the first restart slate; thin posting shrinks the universe by the
  paired-offering rule.
