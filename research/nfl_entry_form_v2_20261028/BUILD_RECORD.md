# BUILD RECORD — NFL_ENTRY_FORM_V2 §7 package (build stage)

**Status: BUILD ONLY — NOT FROZEN, no clock, no counted rows.** This
record documents the §7 package build (construction code, constants
file, fireability test, evaluator adapter, landing check) executed
against the merged design (DESIGN.md + PREREG_DRAFT.md in this
directory; Rocky design review, PR #2849 comment 6463091073). The
freeze itself remains a separate prospective act under PREREG_DRAFT §7:
independent review closed on the exact head, owner authorization, pins,
named first slate. Until then the evaluator adapter refuses every
counted entry point with `EF_V2_FREEZE_NOT_AUTHORIZED`.

## What was built

| Piece | Location |
|---|---|
| Construction (EPA core, veto path, probability map, pick rule) | `sportsedge/nfl_entry_form_v2.py` |
| Constants file (PREREG §7.4 form, build-stage) | `sportsedge/nfl_entry_form_v2_constants.py` |
| Evaluator adapter (v1.1 close rule, §6 kill instruments, refusal) | `sportsedge/nfl_entry_form_v2_evaluator.py` |
| Build-stage fit | `fit_constants.py` + `fitted_constants.json` (this dir) |
| Shared design-data walk for build scripts | `design_data.py` (this dir) |
| Landing check | `landing_check.py` + `landing_check_result.json` (this dir) |
| Family tests incl. the freeze-blocking fireability test | `tests/test_nfl_entry_form_v2.py`, `tests/test_nfl_entry_form_v2_evaluator.py` |

The construction's feature implementation is a faithful port of the
design record's reference implementation (`design_screen.py`): same
shrinkage (250-play prior, 150-play form prior toward the season rate),
same carries (0.30 team / 0.50 QB), same feature definitions. The
build's walk over the pinned inputs reproduces the design record's
eligible-row universe exactly: **1,327 eligible rows** (PINS.json's
count), 2020: 208 / 2021: 224 / 2022: 223 / 2023: 224 / 2024: 224 /
2025: 224.

## Build-stage fit (pooled 2020–2025, fitted once)

- Core margin: intercept (HFA) 1.8157, EPA margin 0.25732, form
  divergence −0.03423. Core total: intercept 45.7744, EPA total
  0.11994, form divergence 0.05602.
- σ (core residual std, floor 12.5): SPREAD 14.0347, TOTAL 13.7368 —
  vs the design-stage walk-forward values 14.40 / 13.95 (PREREG §3);
  the freeze fit governs and re-pins.
- **Fireability (freeze-blocking, PREREG §3):** Φ(3.0/σ) = 0.5846
  (SPREAD) / 0.5864 (TOTAL) ≥ 0.545 ✓; Φ(5.0/σ) = 0.6392 / 0.6421
  ≥ 0.60 ✓. The 0.545 crossing sits at 0.113σ ≈ 1.59 / 1.55 pts, below
  the 3.0 distance gate — the pick rule can fire, and the unit test
  asserts it on the pinned constants.

## Landing check (NON_COUNTED)

2025 Week 10 (14 games) priced end-to-end from the pre-week book state:
28 records (14 SPREAD + 14 TOTAL), 4 SPREAD picks + 5 TOTAL picks
emitted by the rule, all records stamped counted = False /
verified_play = False, closes attached and graded into diagnostics
(SPREAD picks 2–2, TOTAL picks 3–2 at the stand-in lines; accuracy
instrument: SPREAD MAE gap +0.706, TOTAL −0.162 on this slate). All
three counted entry points (count_rows, score_counted, verdict) were
exercised and refused with `EF_V2_FREEZE_NOT_AUTHORIZED` — proof in
`landing_check_result.json`. Stand-ins disclosed there: historical
slates have no DK T-1H snapshots (gap G7), so entry = nflverse
closing-snapshot line at flat −110, close = same line (all READABLE,
CLV 0; moved/failure paths are covered by the adapter's unit tests);
starter identity = recorded starters (named leak class).

## Answer to the design review's open question (§4.2 evidence basis)

Rocky's review asked whether §4.2's agreement evidence (lone-signal
rows 47.3% cover / −7.9% ROI) was measured at ENTRY lines or closes.
**From the design record: closes.** SCREEN_RESULTS.md's method states
every screen grades against the nflverse **closing** snapshot
("vs-close, never verified CLV"), and Screen 3's disagreement row
(n = 315, cover 47.3%, ROI −7.9% at flat −110) is computed with
deviations from that closing snapshot and the residual path fitted on
close residuals. No entry-line measurement exists in the record: no
admitted historical source holds T-1H lines (gap G7), which is
precisely why the construction's claim had to relocate to the entry
snapshot and be judged forward. The §4.2 numbers should be read as
close-based evidence about lone-signal rows, cited as such at freeze.

## Readings taken where the draft's wording needed one (for the freeze package to pin)

1. **Fit shape.** DESIGN §4.1's parenthetical "(2020–2025 walk-forward
   residuals)" sits beside "One OLS fit per market on design data",
   while PREREG §3/§7.4 say the mapping is "fitted once … on 2020–2025
   design data" with coefficients "as fitted on 2020–2025 design data".
   The build follows §7.4's plain text: ONE pooled fit on all eligible
   2020–2025 rows. σ therefore differs slightly from the screens'
   walk-forward means (14.03/13.74 vs 14.40/13.95); both clear the
   floor and the fireability test with room. The freeze fit — whichever
   shape the freeze package pins — governs.
2. **§6.2 CLV-kill units.** "mean same-line CLV ≤ −0.50 pts" is read
   in the shared forward evaluator's CLV units (no-vig probability):
   "pts" = probability points, threshold −0.0050. A line-points
   reading is incoherent on same-line rows (their line CLV is
   identically 0, which would make §5.3's mean-CLV > 0 unsatisfiable),
   so the probability reading is the only consistent one; the freeze
   package should state it explicitly.
3. **Moved direction.** PREREG §8 carries the v1.1 rule in "unchanged"
   but does not spell direction; the adapter implements the pinned
   v1.1 convention of record (NBA team-totals evaluator §6c: favorable
   = the close moved toward the picked side), generalized to spreads
   as HOME up / AWAY down in home-margin units. (The NFL team-totals
   runner labels direction by its own §7 framing; §6c is the v1.1
   original this prereg carries in.)
4. **Two constants sourced from the design record's code.** DESIGN.md
   does not print the QB-delta attempt scale (36) or the pace-deviation
   center (124.0); both are taken verbatim from `design_screen.py`,
   the reference implementation DESIGN §4.2's feature set is defined
   by, and are cited as such in the constants file.
