# PILOT SPEC — NBA Live (In-Play) V0

**Status: PILOT SPEC ONLY — NO IN-PLAY CAPTURE EXISTS — NO CLOCK — NO
PRICES ISSUE FROM THIS DOCUMENT.** Date: 2026-10-28. The lines lane is
pregame-only by law (T-1H + FINAL writes); nothing in this spec changes
that. This document specifies a bounded experiment whose only product
is evidence about whether a live family is buildable at all.

## 1. Why a pilot, and on what machinery

The period construction has one genuinely live-shaped property: its
quarter shares and ratings inputs are pre-tip, but its forecasts
decompose by period — so once quarters are observed, the *remaining*
periods can be re-forecast with observed scores locked in, using the
same frozen fit (`NBA_PERIOD_FIT_V1:310b42f5bc41`) and the same
sufficiency gates. That makes the period engine the only in-tree
candidate for an in-play readout that is a re-application of a screened
construction rather than a new model invented under time pressure.
The pilot tests exactly that re-application — nothing broader.

## 2. Pilot design (terms a future owner go would adopt verbatim)

- **Population:** a predeclared set of 10 regular-season games, named
  before the first one tips. No substitutions; a missed game is a
  missed game and is reported.
- **Checkpoints:** end of Q1, end of Q2 (half), end of Q3, plus the
  FINAL pregame capture as the control. At each checkpoint: record the
  observed period scores, the engine's remaining-period and full-game
  re-forecasts, and DraftKings' in-play lines (game total, spread, and
  the remaining-period totals DK posts) from a rendered board read.
- **Latency discipline (the pilot's real subject):** every checkpoint
  record carries the #2792-style five timestamps (dispatch,
  source-capture, ingestion, durable write, consumption). A quote is
  usable only if its capture-to-decision age is ≤ 60 seconds
  (pilot parameter, to be re-set by any successor preregistration);
  older quotes are logged and refused, never priced from.
- **No automation is claimed:** checkpoint capture is a dispatched
  per-game task, as with pregame due writes. If the cadence cannot be
  met by that mechanism, the pilot's honest output is that finding.

## 3. Readout — what the pilot may conclude

- Forecast quality of remaining-period re-forecasts: MAE vs actuals,
  per checkpoint, against the pregame forecast as the control.
- Market comparison: the re-forecast vs the captured in-play line at
  the same checkpoint (accuracy only — a 10-game pilot grades nothing
  for CLV/ROI and cannot make anything verified).
- Delivery: fraction of checkpoints captured inside the quote-age cap.
  **Graduation bar (predeclared):** ≥ 90% of checkpoints delivered in
  discipline across the 10 games, AND remaining-period MAE no worse
  than the pregame control at the half and Q3 checkpoints. Meeting the
  bar earns only the right to *draft a live preregistration*; missing
  it records the pilot FAILED and the family returns to NO_CONSTRUCTION
  with the evidence attached.

## 4. Activation state and blockers

State reached: **PILOT SPEC ONLY.** Blockers:

- No in-play capture path exists; the pilot needs its own capture build
  and an explicit owner go — it is not authorized by this spec.
- The period-outcomes feed gate from the period preregistration (§4.1
  there) applies identically: without an admitted quarter-score feed,
  even the checkpoints' observed scores have no lawful in-tree source.
