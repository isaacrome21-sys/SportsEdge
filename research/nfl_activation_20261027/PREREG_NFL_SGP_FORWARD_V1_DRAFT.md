# PREREGISTRATION (DRAFT) — NFL same-game parlays: forward test vs captured DraftKings SGP quotes

**Status: DRAFT — NOT FROZEN, NOT IN FORCE, AND NOT FREEZABLE in this
pack.** The leg-dependency, screen, and capture-pilot preconditions
(§7) are all open. Terms are written now so the eventual freeze is a
decision about the joint construction and the menu, not about terms
fitted to outcomes. **Freezing is the owner's act. No game, row, or
slate counts toward this test before its freeze.**

Framework config: `sportsedge/forward_validation/configs/nfl_sgp.json`
(sport NFL, family SGP, `market_form: YES_ONLY` — an SGP quote is a
single price for a joint event; there is no second side).
Construction: `NFL_SGP_JOINT_V1` (`DESIGN_NFL_SGP_JOINT_V1.md`, same
pack) — a joint layer over leg families' committed engines; it owns
no leg marginals.

## 1. The screen that must precede any freeze

On design seasons (2020–2025 — seen data; an entry ticket, never
validation), using the frozen revision's enumerated menu templates
instantiated on historical main lines from the nflverse closing
snapshot (design diagnostic only): the joint engine's predicted
combination hit probabilities must beat the **independence-product
baseline** (same leg marginals, multiplied) on mean log loss over all
menu rows, game-clustered 95% CI entirely below 0, AND must beat it
on Brier score by the same interval rule. A fail is FAILED_SCREEN for
the coupling layer as specified; the marginals are not this family's
to tune.

## 2. Universe, the fixed menu, captures

- **The menu** (enumerated in the frozen revision; templates only —
  leg markets from families satisfying the dependency rule, legs at
  their main lines, 2–4 legs per combination, ≤ 12 applicable
  combinations per game). The menu is part of the frozen package:
  adding, removing, or altering a template after the freeze is a new
  version.
- **Dependency rule (fail-closed):** a combination is priced only if
  every leg's family carries a committed engine with a pinned
  `model_version` at or beyond prereg-draft state. Every row records
  each leg's family, market, line, and model version. If a leg
  family later records FAILED_SCREEN or DOES_NOT_BEAT_MARKET for a
  leg market in use, combinations using that market are suspended
  (not priced; suspension recorded) until that family returns under
  a new version.
- **Captures:** for each game, each applicable menu combination's
  SGP quote is read from DraftKings' SGP builder (rendered pages
  only, the standing lane discipline) at the ENTRY mark (T-1H) and
  the CLOSE mark (FINAL pre-kickoff capture), each with the five
  #2792 receipt timestamps. A quote read at any other time, or for
  any off-menu combination, does not exist for this test.
- **Priced record** (before kickoff, create-only): game, menu
  template id, legs (family/market/line/model_version each), the
  model's joint probability, the entry SGP price + capture
  timestamp, simulation count and seed (the joint engine's Monte
  Carlo settings are part of the frozen package; Monte Carlo error
  on a row's probability must be < 0.005 at the frozen settings,
  verified in the run record).

## 3. Scoring

- **Selection:** PICKED iff the model's joint probability exceeds
  the entry SGP price's raw implied probability. All other priced
  combinations are PASS — reported with their own CLV read, never in
  the verdict sample. (The YES_ONLY selection form, as in the TD
  exotics family.)
- **CLV (PRIMARY):** for PICKED rows, closing raw implied
  probability − entry raw implied probability of the SGP quote.
  Stated bias, carried into every readout: SGP quotes carry a thick
  margin whose *drift* between entry and close counts toward this
  reading exactly as cut drift does on one-sided boards — the bias
  is larger here than in any sibling family and the verdict bar
  (§4) is set with that in view, not adjusted after the fact.
- **Win/loss (secondary):** the combination wins iff every leg wins
  under its own family's settlement (a pushed leg removes itself
  per DK settlement and the combination settles on the rest; the
  row's model probability was recorded for exactly that quantity).
- **Log loss / calibration:** model joint probabilities over ALL
  priced combinations (picked and passed) vs realized joint
  outcomes; decile calibration including the extreme decile. This is
  reported as a first-class readout because an SGP engine's product
  is a joint probability, and a family that wins CLV while its joint
  probabilities are miscalibrated is a warning, not a validation
  candidate — §4's calibration leg has teeth.

## 4. Sample size and verdicts — DRAFT terms

- **No verdict review before ALL of:** 100 graded PICKED rows; 40
  distinct games; 4 full slates priced under the frozen package (a
  slate counts only if the lane captured menu quotes for every game
  on that day's board at both marks). Justification for the row
  gate: menu rows per game are few and longshot-heavy; 100 picked
  rows is the sibling YES_ONLY families' floor and the smallest
  sample on which a clustered CLV interval means anything — adopted
  at the same value, not lowered for a thinner market.
- **Missing-close rule:** a combination whose close quote cannot be
  read at the FINAL capture is `CLV_MISSING` (stays in win/loss, out
  of the CLV average, never filled from another time, source, or a
  recomputed product). Reasons: `NO_CLOSE_ROW`, `MENU_MISMATCH`
  (the builder's offered combination differs from the menu template
  — e.g. a leg's main line moved and the builder substituted an
  alternate; the row is never repriced to the substituted quote),
  `CLOSE_NOT_PREKICKOFF`, `CLOSE_STALE` (>60 minutes before
  kickoff). >20% CLV_MISSING → `INSUFFICIENT_CLOSE_DATA`.
- **Verdict:** `BEATS_MARKET` iff (a) the event-clustered interval
  (§5) for mean CLV on PICKED rows lies entirely above 0, AND (b)
  the calibration leg holds: the model's log loss over all priced
  rows beats the entry raw-implied log loss on the same rows with
  its clustered interval entirely below 0. Otherwise
  `DOES_NOT_BEAT_MARKET`. The burden of proof is on the model.
- **Every readout reports:** graded picked rows; passed rows with
  their CLV read; distinct games; CLV_MISSING count/share/reasons;
  mean CLV + CI; win/loss; log loss (model and entry) over all rows;
  joint calibration deciles; suspensions under the dependency rule,
  by leg family.

## 5. Multiple testing and intervals

Game-cluster bootstrap, 10,000 resamples, seed fixed and recorded at
freeze, intervals two-sided at level 1 − α/k, α = 0.05, k = the
number of families validated or under active forward test in the
program at verdict time (recorded at freeze and review; larger k
governs). Note, stated in advance: this family's k will be among the
program's largest because it freezes last — that is the correct
price of testing many families, not a defect to negotiate.

## 6. Integrity bindings

The menu, engine, leg version pins, simulation settings, and this
document are committed before the first row is priced; captures are
timestamped and pre-kickoff; no retrospective additions (an off-menu
combination that would have won is not a row; it is not data); no
backfilled closes; historical rows never count. A failed verdict is
a result: the joint layer may return only as a new version under a
new preregistration.

## 7. Freeze checklist (owner) — all items open

- [ ] Every menu leg's family at a pinned version (dependency rule
      verified in the run record of a pilot slate).
- [ ] Joint-calibration screen (§1) run and recorded (PASS required).
- [ ] SGP quote capture pilot completed (one slate, both marks,
      receipts complete).
- [ ] Menu enumerated in the frozen revision; independent review
      (CLEARED); seed and §5 k list recorded; freeze by owner ruling
      naming the first counted slate.

*Draft prepared Oct 27–28, 2026 (activation pack). Not frozen.*
