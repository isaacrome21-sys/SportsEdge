# DESIGN — CBB Team Totals + First-Half Lines

**Status: DESIGN ONLY — NO CONSTRUCTION RUN — NO CLOCK.** Date:
2026-10-28. Families entering: CBB team totals and CBB first-half
lines (1H spread / 1H total), both recorded NO_CONSTRUCTION (gap plan,
Oct 27, 2026). DraftKings posts team totals on much of the slate and
1H lines broadly; the capture scope for both already exists (draft PR
#2820, sections TEAM_TOTAL_AWAY / TEAM_TOTAL_HOME / FIRST_HALF_SPREAD /
FIRST_HALF_TOTAL).

Composition note: PR #2350 already claims CBB game/halves and
player-stat foundations (unvalidated). This design composes with that
claim; it reimplements none of it.

## 1. Team totals — a readout of the sides/totals candidate

Team totals need no second model: the expected team points of
`CBB_TORVIK_EFFICIENCY_V1` (see
`CBB_SIDES_TOTALS_DESIGN_AND_PREREG_DRAFT.md` §1) *are* the team-total
forecasts, home and away. The family therefore:

- **Screens inside the §3 design screen of the sides/totals document**,
  as a third leg: team-points MAE, candidate vs (i) a naive team-mean
  baseline and (ii) the simple ratings baseline's team points, same
  pins, same walk-forward protocol, same DESIGN-evidence label. The
  leg passes or fails on its own CI, independently of the spread/total
  legs — a family verdict is never inherited from a sibling leg.
- **Inherits every data gate** of the sides/totals prereg draft
  (live-season Torvik route, admitted crosswalk + Illinois registry,
  capture proof), and its forward terms are the same shape: T-1H
  priced, FINAL-graded, CLV > 0 and ROI > 0 market leg, accuracy leg
  vs the forward-recomputed simple baseline, one verdict at ≥ 40
  distinct graded games.

**Third cross-check (crosswalk cited here, so recorded here):** the
team-score outcomes that grade this family's screen leg are verified
under the same three-way agreement as the parent design — hoopR
substrate, Torvik archive date coverage, and College Basketball
Reference (sports-reference.com/cbb; owner-supplied, Oct 27, 2026)
season schedules confirming fixture, date, and final team scores.
Role: cross-check / reference only — not a ratings input, not a
baseline, not an identity admission; disagreements exclude the fixture
and are logged.

## 2. First-half lines — one extra parameter, one extra data debt

A 1H forecast is the full-game expectation × a **first-half share**
(one share for team points, applied to margin and total alike in V1 —
separate margin/total shares are a V2 question the data must earn).
Torvik carries no half splits, so the share cannot come from the
ratings source. It must be fitted from historical play-by-play:

- **Named prerequisite (outstanding):** hoopR play-by-play release
  assets (`load_mbb_pbp` family) pinned by the full-tuple rule of
  draft PR #2835 **with schema verification** — #2835 pinned schedules
  and player box (the latter on bytes+hash only, schema
  documented-only), and pinned no PBP asset. Until a PBP manifest with
  a verified schema lands, the half share cannot be fitted and **1H
  is not screenable**. No share is borrowed from the NBA fit, from a
  rule of thumb, or from halving final scores — the season-prep
  contract (`research/cbb_season_prep_20261020/`) already refuses
  half-of-final as an outcome source, and this design concurs.
- **Screen shape (once the prerequisite lands):** the share is fitted
  on seasons strictly before each scored season; 1H outcomes are
  derived from the pinned PBP itself; metrics are 1H-total MAE and
  1H-margin MAE vs a naive half-share climatology baseline, same
  DESIGN-evidence label. College Basketball Reference may corroborate
  team-score outcomes as in §1; any use of its pages for half splits
  requires the screen's data audit to first verify that coverage —
  it is not assumed.
- **Forward terms** then mirror §1's, against the #2820 FIRST_HALF
  sections, under the same three data gates. Illinois-college fixtures
  refused fail-closed, identically.

## 3. Activation state and blockers

State reached: **DESIGN** — team totals fully spec'd as a screen leg +
forward family on the parent construction; 1H reduced to one named
data prerequisite. Blockers, one line each:

- Team totals: inherits the parent family's three blockers (live
  Torvik route; crosswalk admission; historical results pin).
- 1H: no pinned, schema-verified play-by-play asset exists — the half
  share cannot be fitted until one lands.
