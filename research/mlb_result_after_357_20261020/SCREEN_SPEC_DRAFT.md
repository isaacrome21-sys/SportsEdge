# Proposed one-shot historical screen: Result After Nth Inning (3-way)

**Draft / unfrozen.** Author before implementing the adapter and before any historical scoring. Owner may approve/freeze evidence and screen; until then the historical screen is NOT RUN and none of the readouts are valid wagers.

## Construction lock

* v1 readout = mechanical repackaging of existing frozen-capability `F3_MONEYLINE`, `F5_MONEYLINE`, `F7_MONEYLINE` probability readouts. `HOME` and `AWAY` probabilities are passed unchanged. `TIE` = the *underlying period moneyline's push probability*, with **no redistribution of tied score mass**. For three-way settlement, `push_probability=0`: TIE is a distinct winning selection.
* Applicable only `RESULT_AFTER_INNING_3`, `RESULT_AFTER_INNING_5`, `RESULT_AFTER_INNING_7`. No new model, dispersion, sample threshold, smoothing or hyperparameters; depend on already scored cumulative F3/5/7 distributions.
* `RESULT_AFTER_INNING_2`, `_4`, `_6`, `_8` are explicit NO_CONSTRUCTION/NO_CUMULATIVE_JOINT refusals until independent point-in-time constructions exist. Per-inning `INNING_N_*` is an unrelated market, remains held.
* No price intake or canonical routing. Existing `sportsedge.mlb_per_inning_gates` stays byte-identical, with deployment/state unchanged, `NO_MARKET_TEST`, `eligible=false`.

## Evidence and scoring (only after owner approval)

Target 2025 MLB regular season, gamePk-identified and completed through the target inning under an explicit settlement policy. Consume only certified historical inning results *observed and available before the fixture scheduled first pitch* for model features. Results for the target fixture are postgame settlement data only and never enter the features. Reject conflicting MLB gamePk/team identities, same-day results whose observed-at could not precede the target fixture, suspended/shortened or unverified through-N-innings games, and any unpinned snapshot. Record archive manifest SHA-256 and each source/feature SHA-256.

**Parity screen**: For every admitted fixture and N in {3,5,7}, compute three outputs and compare their numerical probability vector exactly to the incumbent moneyline home-win, away-win, and *push* readouts. These must conserve to 1 within 1e-12 and preserve tie mass. A single mismatch is a failure.

**Chronological calibration screen**: Multiclass Brier and multiclass log loss for the 3-way HOME/TIE/AWAY outcome. Compare on exactly the same fixtures to strictly-prior, season-to-date (previous-season fallback only when explicitly pinned) 3-class climatology with Jeffreys alpha 0.5 per class. Use per-date block-bootstrap 95% CI for candidate-minus-baseline metrics. Predeclare a family verdict for EACH period: `BEATS_BASELINE` only if both metrics improve and each CI upper bound is below zero; else `DOES_NOT_BEAT_BASELINE`, or `INSUFFICIENT_DATA` if the pinned history/support gate is unmet. Do not select/adjust any construction or threshold after seeing results.

No historic paired and timestamped DraftKings three-way lines are established. Even `BEATS_BASELINE` in this calibration does not equal market validation, eligibility, PLAY, or model promotion. All quote-based validation remains `NO_MARKET_TEST` until independently admitted.

**Run status:** NO EXECUTION. Source manifest / PIT feed hashes unavailable in this build. NO numeric metrics, unearned test counts, or historical verdict claimed.
