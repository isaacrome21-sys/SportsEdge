# Lane A Recalibration + Disagreement Guard — ADOPTION RECORD

**Date:** 2026-10-28 · **Act:** owner-delegated adoption · **Status after
this record:** recalibration layer ADOPTED (still UNVALIDATED);
≥6-point disagreement guard ADOPTED as a standing card gate.

## The delegation

On Oct 28, 2026, after the Lane A margin-compression diagnosis (see
`BUILD_RECORD.md` in this directory and the calibration diagnostic of
the same date), Rocky presented Isaac with the two proposals in an
options widget — adopt the recalibration layer (#2874), adopt the
≥6-point model-vs-market margin-disagreement guard, adopt both, or
extend the one-day NBA hold. Isaac answered in chat (~15:44 CT):
**"Do what you think is best."** That answer delegates this decision;
this record is the decision and its reasons. Isaac can reverse any
part of it with a word, and reversal is a new record, not an edit of
this one.

## The decision — adopt BOTH

1. **Recalibration adopted.** The Lane A vNext layer
   (`sportsedge/lane_a_recalibration.py`) is the probability basis for
   operative Lane A card placement from this act forward:
   `p_used = implied + k·(model_p − implied)`, k re-estimated from
   the trailing graded record, floored at 0, EV derived from
   `p_used`. The adoption-time estimate is the diagnostic's own fit:
   183 decided legs, k_raw = −0.461 → **k_used = 0**. Consequence,
   stated plainly: at k = 0 every Lane A effective EV is ~0 and **no
   Lane A row headlines** until the graded record earns a positive k
   under the refit rule below. That is the point — the model's
   deviations from market price were anti-informative in the graded
   sample (pooled Brier 0.2740 model vs 0.2404 market-implied;
   shrink fit k = −0.46), so the honest claimed edge today is zero.
2. **Disagreement guard adopted.** Independently of EV, any NBA/NFL/
   CFB row whose model projection disagrees with the market by
   **≥ 6.0 points** is placed in the overconfidence bucket: projected
   home margin vs the market home margin implied by the game's
   spread pair (SPREAD and ML rows), projected total vs the market
   total line (TOTAL rows). This is the structural repair for the
   Oct 28 failure mode — heuristic margins compressed into −0.4..+4.5
   against market spreads to 13.5, producing six same-shaped underdog
   rows at +33.7–39.4% EV, one or two points under the +40% wire.
   The guard fires on the disagreement itself, so a future
   compression cannot leak under the EV wire again, including after
   k turns positive. MLB is outside the guard (its run line is a
   fixed 1.5 handicap, not a market margin estimate); recalibration
   applies to MLB rows as to all Lane A rows.

## Wiring

`sportsedge/lane_a_card_gates.py` (`LANE_A_CARD_GATES_V1_ADOPTED_20261028`)
is the card-build boundary: it applies the recalibration to every
Lane A priced row, measures the disagreement, and stamps each row
with a `card_gate` block (effective EV, disagreement points/kind,
guard state, bucket, reason). Gate order: recalibration-not-applied →
BLOCKED (fail-closed); guard triggered or effective EV ≥ +40% →
OVERCONFIDENCE; guard not evaluable in a guard-scope sport → BLOCKED;
price < −165 → EXCLUDED; effective EV ≥ +3% → HEADLINE; otherwise
EXCLUDED. The pre-existing gates (the +3% floor, the +40% bucket, the
−165 cap) are unchanged in value — they now read the **effective**
EV. Fact-based withholds (Tier-1 injury blindness and successors)
remain a separate card-build step after these gates, unchanged.
`RECALIBRATION_ENABLED` in the layer module now defaults to True;
the gates pass `enabled=True` explicitly regardless.

## Refit rule

k is re-estimated from the trailing graded record (decided WIN/LOSS
legs carrying a printed model probability — the diagnostic's
universe) once **~180 further decided legs** beyond the adoption-time
183 have graded, and at each subsequent ~180-leg increment. A refit
that is negative, degenerate, or below sufficiency leaves
k_used = 0. k is never hand-set, never fitted on a partial day, and
never allowed below 0 (the layer can only shrink claimed edges
toward the market, never amplify or reverse them). Each refit is
recorded with its n, k_raw, interval, and source before it governs a
card.

## What this act does NOT do

- It validates nothing. Lane A and the recalibration layer remain
  UNVALIDATED research; every row stays LEAN / unvalidated estimate,
  verified_play = false, PAPER / 0u. No PLAY eligibility changes.
- It touches no frozen construction, evaluator, prereg, or pin —
  `artifacts/free_models.py` is byte-untouched (the layer wraps its
  output, as designed in #2874).
- It does not reopen the Oct 28 card: today's card stands as built
  and disclosed, and tonight's Threads posts remain under the
  date-scoped NBA hold Isaac directed earlier today. The adopted
  gates govern cards built from Oct 29, 2026 forward.
- It does not decide any other pending owner act (CBB Amendment 2,
  PGA Amendment 1, EFV2 freeze — all separate, all still Isaac's).

## Verification (this PR)

- Recalibration family tests updated for the adopted flag default
  (flag-off behavior still pinned by explicit `enabled=False` calls,
  including the golden-hash byte-identity of the untouched engine).
- New gate tests reproduce the Oct 28 failure rows from the real
  card numbers (Wizards +10.5 disagreement 7.35; Pelicans +5
  disagreement 8.24; the Clippers +5.5 case at 5.74 shows the guard
  alone would have missed it and the recalibration catches it),
  plus positive-k headline/guard paths, the total guard, the MLB
  guard-scope exclusion, and both fail-closed paths.
