# Lane A vNext Probability-Recalibration Layer — BUILD RECORD

**Date:** 2026-10-28 · **Branch:** `rocky/lane-a-recalibration-vnext-20261028` · **Base:** main `ddd92a3`

## Status, stated plainly

- This layer is **UNVALIDATED**. Nothing in this PR validates it; the
  diagnostic that motivated it is itself a graded-record diagnostic,
  not a validation.
- It is **NOT ADOPTED**. Adoption is an **owner decision, still
  pending**. This PR is a build only.
- It is **NOT WIRED into card production**. No production code imports
  or calls the module. The config flag `RECALIBRATION_ENABLED` in
  `sportsedge/lane_a_recalibration.py` defaults to **False**, and no
  file in this PR sets it True anywhere.
- With today's graded record, the layer would present **~zero claimed
  edge**: the shrink fit on the pooled Oct 23–27, 2026 record is
  k = −0.461, floored to **k = 0**, so `p_used` collapses to the
  market break-even probability and every recalibrated EV is exactly
  zero. That consequence is the point of the diagnostic — the model's
  disagreements with market price carried no positive signal in 183
  graded legs (pooled Brier 0.2740 for the model vs 0.2404 for the
  market-implied probabilities on the model's own selections) — and it
  is stated here, not buried.

## Basis

EV-band calibration diagnostic, 2026-10-28
(`calibration_diagnostic_20261028/REPORT.md` in the operative records;
summary values used here: `calibration.brier_n_legs = 183`,
`calibration.brier_model_p = 0.2740`,
`calibration.brier_market_implied = 0.2404`,
`calibration.shrink_fit_k_pooled = -0.461`). Its one supported
adjustment, for the unfrozen Lane A research model only: insert
`p_used = implied + k·(model_p − implied)` between the raw model
probability and EV computation, with k re-estimated from the trailing
graded record and floored at 0, and EV / headline eligibility / bucket
placement derived from `p_used`. Card gates themselves are unchanged
by the diagnostic's recommendation and are not touched here.

## What was built (new files only)

1. `sportsedge/lane_a_recalibration.py` — the layer.
   - `estimate_k(rows)`: least-squares refit of k from graded rows
     (decided WIN/LOSS legs carrying both a model probability and a
     market-implied probability; pushes and probability-less rows do
     not count — the diagnostic's universe). Reports the unfloored fit
     as `k_raw`, its standard error and 95% interval, and applies it
     floored at 0 as `k_used`.
   - Sample-size honesty: below **180** decided legs with a printed
     model probability (the diagnostic's stated sufficiency for
     refitting k), the estimate reports `k_used = 0`, `k_raw = None`,
     reason `INSUFFICIENT_SAMPLE` — no noisy point estimate. A record
     with zero model/market deviation reports
     `DEGENERATE_NO_MODEL_DEVIATION` instead of a fake zero fit. The
     diagnostic's further caveat is carried in the module docstring:
     roughly 180 *additional* decided legs beyond the current 183 are
     needed before a refit interval is usable for an adoption
     decision; the interval is reported so its width is visible.
   - `estimate_k_from_summary(summary)`: applies the same sufficiency
     + floor rules to a summary.json-shaped diagnostic record
     (`calibration.brier_n_legs`, `calibration.shrink_fit_k_pooled`).
     On the 2026-10-28 diagnostic it reproduces k_raw = −0.461 →
     floored k_used = 0, reason `NEGATIVE_FIT_FLOORED_AT_ZERO`.
   - `apply_recalibration(result, estimate, enabled=...)`: with the
     flag off, returns the input object **unchanged** (same object).
     With the flag on, returns a deep copy adding a `recalibration`
     block: `p_used`, the p_used-derived `ev_per_dollar`, and the raw
     `model_p` / `implied_p` / `ev_per_dollar_model_p` beside it. The
     engine's own fields are never overwritten and the caller's object
     is never mutated; one log line per priced row records both the
     raw `model_p` and `p_used`. A row that cannot supply the Lane A
     numbers comes back visibly marked `NOT_APPLIED_INPUT_MISSING`,
     never silently passed as recalibrated. `effective_probability` /
     `effective_ev` expose the values gates would use under adoption.
   - Anchoring: for a Lane A priced row, `implied_p` is the Lane A
     view's `book_break_even_p` — the push-consistent market
     break-even, which equals the diagnostic's raw price-implied
     probability whenever the push probability is 0. EV is recomputed
     with the engine's own formula (`win·(dec − 1) − loss`).
2. `tests/test_lane_a_recalibration.py` — 20 tests (see Verification).
3. This record.

## Why the layer wraps Lane A output instead of editing the engine

`artifacts/free_models.py` is hash-pinned by a FROZEN construction:
`sportsedge/nfl_team_total_runner.py` records
`artifacts_free_models_sha256` and imports Lane A from that file.
Editing the engine would move a frozen pin. The layer therefore sits
on the engine's priced-result dicts, downstream of `calculate` /
`run`. **No frozen construction or evaluator is touched; no existing
file of any kind is modified by this PR** (the diff is three added
files).

## Verification (Rocky-run, this build)

- New tests: **20 passed** (`tests/test_lane_a_recalibration.py`),
  covering: flag default False; flag-off object identity at the apply
  seam; k re-estimation on the diagnostic's pooled record
  (183 legs, k_raw −0.461 → floored 0); rows-refit negative fit
  (analytic k = −0.70 → floored) and positive fit (analytic k = +0.50
  → kept, with CI); insufficient sample at 179 legs and with
  pushes/unprinted rows excluded (160 counted of 240 rows); degenerate
  zero-deviation record; floor behavior (k = 0 ⇒ p_used = implied ⇒
  derived EV exactly 0); negative k refused by name
  (`RECALIBRATION_K_NEGATIVE`); applied-row math at k = +0.50
  (p_used 0.57, EV 0.088182 at −110); raw values preserved and caller
  object unmutated on both a synthetic row and a real engine-priced
  row; missing-view rows visibly not applied; log shape (one line per
  priced row containing both `model_p=` and `p_used=`; silence with
  the flag off).
- **Flag-off byte-identity proof, two independent ways:**
  1. A fixed offline fixture (MLB totals pair + NBA ML pair + NBA
     spread pair, fixed `now`, fresh quotes) was run through
     `artifacts/free_models.run` on pristine main BEFORE any layer
     code existed, in two separate processes: canonical JSON
     (sort_keys, compact separators) sha256 =
     `644d078d2c9c759782765cb64c595c763b79ec9959621a7cea53b584e2804535`
     (56,693 bytes). Re-run on this PR's tree — and inside the test
     suite as a golden-hash test — the digest is **identical**, and
     the serialized card contains no `recalibration` or `p_used`
     bytes.
  2. `apply_recalibration` with the flag off returns the **same
     object** (`out is result`), and `apply_recalibration_to_rows`
     returns the same list object — no code path exists by which the
     disabled layer can alter a byte of pricing output.
- Regression spot-check: existing Lane A suites
  `tests/test_anchored_lane_play_gate_20261012.py` +
  `tests/test_cfb_lane_b_retired.py` — **15 passed**.
- Ruff gate (`--select E9,F821,F822,F823,F811`) on both new Python
  files: clean. No new dependencies (stdlib only).

## What adoption would still require (not in this PR)

An owner ruling; a wiring change at the card build that applies the
layer to Lane A rows and derives headline/bucket placement from
`effective_ev`; and a trailing-record refit cadence. Until then this
module is inert: present in the tree, flag off, called by nothing.
