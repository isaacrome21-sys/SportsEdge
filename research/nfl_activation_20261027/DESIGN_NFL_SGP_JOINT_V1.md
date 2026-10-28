# DESIGN — NFL same-game parlays: `NFL_SGP_JOINT_V1`

**Status: DESIGN ONLY — the last family in the pack to activate, by
construction.** Family before this pack: NO_CONSTRUCTION (SGP material
captured inside issue comments; `docs/market_coverage_phase7.md`
records SGPs as NOT_WIRED — "correlation modeling out of scope").
PAPER / research only.

## 1. What an SGP price actually is — and where it can be wrong

A DraftKings same-game parlay quote is a single price for the joint
event that several legs in one game all win. DK does not price it as
the product of the leg prices: its engine applies correlation
adjustments and then a margin that is materially thicker than the
straight-bet margin. Two consequences define this family's honest
shape:

- **The naive product is not the baseline to beat — the DK SGP quote
  is.** A model that merely multiplies leg probabilities will "find
  edge" against the product everywhere and against the actual quote
  almost nowhere, because the quote already contains the adjustment
  and the margin. This design therefore validates against captured
  SGP quotes (entry and close), never against a computed product.
- **Where a consistent joint model can still disagree:** DK's
  correlation adjustments are necessarily coarse — a finite set of
  correlation buckets applied to leg-type pairs. A model that
  simulates the game once and reads every leg off the same simulated
  game produces joint probabilities that are consistent with the
  *specific* matchup (this QB's volume against this defense, this
  game's pace and script distribution), including dependence the
  bucket system cannot express: QB yards ↔ WR yards ↔ team total ↔
  spread all moving together through game script (a team trailing
  late throws more, scores differently, and its opponent runs more).
  The claim is narrow: matchup-specific joint structure, estimated
  honestly, differs from bucketed adjustments somewhere. The forward
  test exists to find out whether "somewhere" survives the margin.

## 2. The construction

`NFL_SGP_JOINT_V1` is a **joint layer over the leg families' engines —
it owns no leg marginals.** For a game, it draws joint game states
from a simulation whose marginals are *bound to* the leg engines'
committed distributions:

- Team scores: the joint distribution implied by
  `NFL_TEAM_TOTAL_DIST_V1` for both teams, coupled through a shared
  game-environment factor (pace/total variance shared across teams —
  the two team totals are not independent, and the coupling parameter
  is estimated from point-in-time residuals on design seasons and
  fixed in the engine, never fit per game).
- Player stats: the Part 2 / Part 2B evaluators' per-player
  distributions, conditioned on the simulated game state through
  each construction's own structure where it has one (e.g. team
  passing volume scales with simulated team plays and script);
  where a leg construction is a marginal-only distribution, the
  joint layer couples it to the game state via its correlation to
  the simulated team outcomes, with the coupling estimated the same
  way and frozen.
- Every leg outcome in a combination is read off the **same**
  simulated game. A combination's model probability is the share of
  simulated games in which all its legs win (pushes handled per leg
  family's own rules; a pushed leg re-prices the combination per DK
  settlement — the leg is removed and the combination settles on the
  remaining legs, and the model's probability for the row is the
  corresponding conditional quantity, recorded as such).

**Version binding (the dependency rule, hard):** every SGP row
records each leg's family, market, and `model_version`. A combination
may only be priced when **every** leg's family carries a committed
engine at or beyond prereg-draft state with a pinned version. If a
leg family later records FAILED_SCREEN or DOES_NOT_BEAT_MARKET for
the leg market used, SGP rows using that leg market are suspended
fail-closed (not priced, suspension recorded) until the family
returns with a new version — an SGP built on a failed leg would
launder the failure. The SGP layer itself has exactly one versioned
artifact: the coupling/simulation engine, hash-pinned at freeze.

## 3. The capture problem — a fixed menu, or there is no test

An SGP quote exists only for a combination someone builds. There is
no "board" to capture, so the market baseline must be manufactured
by design: **a fixed combination menu, committed at freeze.** The
menu is a finite list of combination templates (leg patterns, e.g.
{game total OVER, QB pass yards OVER, WR1 receiving yards OVER} with
each leg at its main line), enumerated in the frozen package. For
each game, the lane prices exactly the menu's applicable
combinations: the SGP quote is read from DK's SGP builder for
precisely those legs (entry capture at the standing T-1H mark, close
capture at the FINAL mark), with the five #2792 receipts per quote.
Quotes for combinations off the menu are never captured, never
priced, never graded — a bettor-built market cannot be backfilled
into a test after outcomes are known, and this rule is the family's
main integrity risk, closed here in advance. Menu size is set so a
slate yields a bounded number of quotes (target ≤ 12 per game); the
frozen revision of the prereg draft enumerates the templates.

Capture feasibility note, stated plainly: reading SGP builder quotes
is a rendered-page task (the standing lane discipline: rendered
pages only, never the DK API), slower per quote than a board read.
The pilot for this capture is part of the live family's
infrastructure discipline (receipts, latency budgets) and is a named
step below, not an assumption.

## 4. Named missing steps, in order

1. **Leg engines at pinned versions:** team totals (this pack —
   ARMED pending freeze), Part 2 / Part 2B props (frozen tests
   running), game lines (a successor construction for the retired
   sides/totals family — not this pack's to design). SGP's menu can
   only include legs from families that clear this bar at SGP's
   freeze.
2. **Joint-calibration screen:** on design seasons (2020–2025,
   seen data), the simulation's joint hit rates vs realized
   co-occurrence for the menu's leg patterns, against the
   independence-product baseline built from the same marginals.
   Criteria are fixed in the prereg draft (§1 there) — the screen
   asks the only question that matters pre-freeze: does the coupling
   layer predict co-occurrence better than independence?
3. **SGP quote capture pilot:** one slate, menu quotes at both
   marks, receipts complete — proving the lane can read builder
   quotes inside the cadence before any clock depends on it.
4. Owner freeze of the prereg draft with the menu enumerated.

Until steps 1–3 land: **DESIGN ONLY**; framework config
(`nfl_sgp.json`) carries `model_version: "UNPINNED"` (a sentinel no row can match, so every row is refused fail-closed), and its leg
dependency rule is recorded in the config itself.
