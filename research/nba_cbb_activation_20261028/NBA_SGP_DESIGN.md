# DESIGN — NBA Same-Game Parlay (SGP) V1

**Status: DESIGN ONLY — NO CONSTRUCTION EXISTS — NO CLOCK.**
Date: 2026-10-28. SGP is a *derived* family: it can never be more
validated than the leg families it combines, and this design is written
so it can never become a side door into a family that is closed,
blocked, or quarantined.

## 1. Leg eligibility — the whole design in one rule

An SGP leg may come only from a family whose own state permits its
prices to be used, and the SGP inherits the **weakest** leg's state:

| Candidate leg family | State today | SGP-eligible? |
|---|---|---|
| Period totals (this packet's prereg draft) | DRAFT_NOT_IN_FORCE | Only after that prereg freezes and its data gates hold |
| Team totals | ARMED under PR #2504 (receipt act outstanding) | Only as that family's own terms allow |
| Sides / totals (successor, PR #2786) | DESIGN, baseline-blocked | No — deferred with the family |
| **Player props (any)** | **V2 QUARANTINED (owner ruling Oct 27, 2026)** | **NO — excluded absolutely while the quarantine stands** |

No leg may be sourced from a retired construction (DIST_V1 signals
included). If a card's SGP menu offers legs this design excludes, the
SGP is simply not priced — the menu never expands the family.

## 2. Construction shape (to be built only when §1 admits legs)

DK's SGP price embeds the book's own correlation model plus hold; the
only honest counter is a **joint distribution built once per game**, so
that correlation is structural rather than bolted on:

1. Simulate the game's quarter-score paths from the period engine's
   distributional extension (the named Phase A task in
   `NBA_GAME_PROPS_DESIGN.md`), with observed pre-tip inputs only.
2. Derive every eligible leg's outcome from the *same* simulated paths —
   period totals, team totals, and (when lawful) game lines are then
   jointly distributed by construction.
3. The SGP probability is the path frequency of the conjunction; the
   price comparison is against DK's offered SGP price for the identical
   leg set, captured at T-1H and FINAL under the standing cadence.

In-tree quarter-path allocation machinery exists
(`sportsedge/sports/nba/periods.py` — quarter shares as versioned inputs
over simulated team paths); it is cited as existing code only. Because
adjacent simulation constructions include a retired one (DIST_V1), any
reuse requires its own review, and this design adopts nothing by
reference.

## 3. Validation shape (for a future preregistration)

Three baselines, all predeclared: (a) the **independence product** of
the legs' own model probabilities — the joint model must beat it on
Brier / log loss, or the correlation layer is worthless; (b) **DK's
offered SGP implied probability**, hold disclosed — the market leg,
graded by CLV against the FINAL-capture SGP price and ROI at captured
entry prices; (c) the legs' families' own baselines, inherited. One
verdict at a predeclared minimum sample of graded SGPs; anti-peeking;
a failed verdict retires this version.

## 4. Activation state and blockers

State reached: **DESIGN ONLY.** Blockers:

- No leg family is yet in a state that lets SGP legs price (period
  prereg unfrozen, its data gates open; team-totals receipt act
  outstanding; sides/totals blocked) — SGP activates last, by
  construction, not by choice.
- The joint-path distributional extension is unbuilt (shared with game
  props Phase A).
