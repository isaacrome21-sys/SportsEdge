# MLB same-game parlay (SGP) — construction design + preregistration draft

**Status: DESIGN ONLY — preregistration DRAFT, not frozen. No clock, no
verified claim, no PLAY.** This design prices DK Same Game Parlay
combinations for a single MLB game from one shared simulation, so leg
correlation is modeled rather than assumed away.

## Why SGP is its own family

An SGP price is a joint probability. DK's SGP odds embed the book's own
correlation assumptions, discounted. A leg-by-leg edge multiplied together
is not an SGP edge: independence overstates the joint probability of
positively-correlated legs and understates it for negatively-correlated
ones. The family therefore validates the JOINT distribution, not the legs.

## Edge mechanism

One plate-appearance-level game simulation generates every leg from the
same simulated game: pitcher workload chain (design #1's BF/pitches/outs
machinery), batter PA outcomes from the successor batter research line,
team run totals, and game result. Legs drawn from one simulated game carry
their true correlation — a pitcher's outs and his team's win probability
move together inside the sim because they are the same game. The candidate
edge is the gap between the sim's joint probability and DK's SGP implied
probability, where DK's correlation discount is shallowest on the
combinations casual bettors over-demand (ace overs + favorite + star
batter overs).

## Inputs and leg dependency (hard rule)

Legs may only be drawn from market families whose constructions exist in
the program: game lines (MLB_GAME_DIST line of work), pitcher props
(K ridge; extension design #1), batter props (successor design line). A leg
whose family has no construction is not priceable and may not appear. The
SGP family's validation verdict is capped by its legs: an SGP PASS requires
every leg family used in the validated universe to have passed its own
validation; if a leg family is merely screened or design-stage, the SGP
result is reported as a SCREEN result for the joint machinery, not a
validation pass. This dependency is stated here so it cannot be forgotten
at verdict time.

## Construction

- 20,000 simulated games per fixture from the shared PA-level sim, seed
  fixed per fixture and recorded (determinism contract mirrors the repo's
  existing simulation receipts).
- Joint probability for a requested combination = simulated frequency,
  with a minimum-frequency floor: combinations with simulated frequency
  below 0.2% are reported as tail-unstable and excluded from the validated
  universe (fixed here).
- DK SGP price taken from the rendered SGP builder surface at capture;
  where DK refuses a combination, it is out of the universe (no
  substitution, no reconstruction).

## Validation protocol (fixed in advance; one look)

Universe: DK-posted SGP combinations on 2027 regular-season games whose
legs all come from validated families, captured pregame, over a 60-day
window starting the first day the leg-dependency rule is satisfiable;
minimum 200 priced combinations. Comparators on identical combinations:
(a) the independence product of the leg constructions' probabilities —
the "existing model" for a joint claim is the legs multiplied as if
independent, which is exactly the error this family exists to beat — and
(b) DK's SGP implied probability. Primary metric: mean log loss on the
binary combination outcomes. PASS = joint model beats BOTH (a) and (b) at
alpha = 0.05 / k, calibration slope within [0.8, 1.25]. One look. CLV on
SGP prices is reported where a close capture exists; it does not gate.

## Activation state on landing

DESIGN ONLY, and explicitly last in the MLB order: the leg families
(2027 forward windows) gate this family's first possible validation to
mid-2027 at the earliest. The joint-sim machinery can be built and
screened on design data in the meantime; the screen is design evidence.

## Blockers

- Leg dependency (above) — scheduling, not data.
- DK SGP capture: the lane does not currently capture SGP builder prices;
  a capture extension (rendered page, pregame, paired with the game's
  T-1H/FINAL writes) is owed before any window is scheduled.
