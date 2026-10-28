# SCREEN REPORT — NHL_TEAM_TOTAL_DIST_V1 design screen (attempt 1)

**Verdict: NOT_EXECUTABLE — the design specifies no runnable screen
today, and its one validation protocol is forward-only behind gates
that have not opened.** No PASS or FAIL is recorded; the family state
is unchanged (DESIGN ONLY, not frozen, no clock). No criterion was
edited, no substitute data used, no historical backtest invented.
Construction build verification is recorded separately in
`BUILD_RECORD.md` (fixture rates; not a screen).

## The validation protocol the design actually specifies (verbatim)

From `NHL_TEAM_TOTALS_DESIGN.md` (PR #2839), "Validation protocol
(fixed in advance; one look)":

> "Runs inside the parent's Stage B window (Dec 1, 2026 – Jan 31,
> 2027) on games with paired DK team-total captures; minimum 200
> team-games per side (home/away pooled with a side indicator, fixed
> here). Comparators: (a) the implied-split distribution — game-total
> distribution split by the closing moneyline-implied share, i.e. the
> "existing model" for this family is the market's own derivation,
> made explicit; (b) DK team-total no-vig probabilities at the
> offered lines. Primary metric: log loss on the team-total
> over/under outcome at the offered line. PASS = candidate beats BOTH
> at alpha = 0.05 / k, one look with the parent's Feb 1, 2027
> verdict."

Activation gate (same document):

> "If the parent's Stage A fails, this family's window does not open
> (the rates it prices from are the parent's construction)."

Parent design (`NHL_SIDES_TOTALS_DESIGN.md`), Stage B precondition:

> "Precondition: Stage A verdict = PASS on Nov 30, 2026, and NHL
> capture flowing under the restart pack."

## Verdict per criterion

| # | Criterion (per the protocol above) | Result |
|---|---|---|
| 1 | Candidate log loss beats comparator (a) implied-split distribution, one-sided at alpha = 0.05 / k, one look Feb 1, 2027 | **NOT RUN** — gaps G-TT-1…4 |
| 2 | Candidate log loss beats comparator (b) DK team-total no-vig probabilities at the offered lines, same terms | **NOT RUN** — gaps G-TT-1…4 |

n team-games (either side): 0. No fixtures priced, no fitting, no
look taken — the protocol's one look is preserved intact for its
window.

## The gaps (each independently sufficient)

- **G-TT-1 — No historical screen exists in the design.** The
  protocol quoted above is the family's ONLY validation: forward,
  inside the Dec 1, 2026 – Jan 31, 2027 window, on paired DK
  captures. No seasons, baselines, or criteria for a historical
  backtest are named anywhere in the design, and the parent design
  states "No historical NHL closing archive is claimed." A
  retrospective screen would have to invent both its data and its
  criteria; neither was done.
- **G-TT-2 — The Stage A gate has not opened and cannot yet be
  passed.** The parent's Stage A verdict is locked to Nov 30, 2026;
  today is Oct 28, 2026. The design's rule is explicit: if Stage A
  fails, this family's window does not open — and until it passes,
  there is no window to run in.
- **G-TT-3 — The qualifying capture universe is zero.** The protocol
  requires games with paired DK team-total captures inside the
  window and a minimum of 200 team-games per side. The window opens
  Dec 1, 2026. NHL capture restarted Oct 28, 2026, and the design's
  own blocker stands open: "DK team-total presence/depth on NHL
  event pages must be confirmed in the first restart slate; thin
  posting shrinks the universe by the paired-offering rule."
- **G-TT-4 — No parent fitted rates exist to price with.** The
  family has no separate fit by design ("same fitted rates" as the
  parent), and the parent design records the state on main: "no
  frozen NHL rate artifact exists on main today — the card correctly
  reports NO_MODEL until one does." Until the parent build lands its
  artifact, the candidate distribution cannot be produced for any
  real game. (The construction built alongside this report prices
  disclosed fixture rates only, as build verification.)

## Unblock path

Parent rate artifact lands → Stage A verdict Nov 30, 2026 = PASS →
DK team-total depth confirmed on restart slates → paired captures
accrue through the Dec 1, 2026 – Jan 31, 2027 window (≥200
team-games per side) → the protocol runs exactly as quoted, one look,
Feb 1, 2027. Nothing in this report amends any of those terms.
