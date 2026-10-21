# NFL/NBA RUN IT research-annex build report — 2026-10-20

**Branch:** `feat/nfl-nba-runner-annex-recovery-20261020`  
**Starting main:** `7a189b001a8f3a1beb2b1dfe554d400baac3323d`  
**Status:** DRAFT / BUILD ONLY — **NOT VERIFIED**, **NOT MERGE-READY**.

## What and why
* `artifacts/run_it_full.py` delegates to an isolated annex through explicit operator-evidence kwargs and separate optional CLI files. It never obtains engine history, fixture pins, or model identity from untrusted issue/line payloads.
* `sportsedge/research/nfl_nba_engine_card_annex.py` invokes existing NFL v1 prop `price_nfl_prop` and NBA `price_game` without altering either model's scored construction.
* Every readout is research-only; NFL probabilities are not surfaced as candidate, EV, play, or staking guidance. NBA produces point totals and period point forecasts, **not** fabricated outcome probabilities.
* Fixture event, model-athlete ID (via pinned NFL `player_id_map`), point-in-time start, operator history pins, native two-sided DK quote pair, 180s freshness/120s pair span, venue, and registry-independent quote form are checked with named refusals. The interception mapping deliberately distinguishes quarterback interceptions thrown from defensive player interceptions.
* The operator supplies three independent JSON inputs: `--annex-history-json`, `--annex-fixtures-json`, and `--annex-pins-json`. PIN provenance remains an **operator responsibility**; this adapter checks equality, not the independent acquisition of the pin. `--annex-period-source` is optional for the frozen NBA period-fit construction.
* The prior local-session branch `feat/nfl-nba-runner-wiring-20261021` was not on origin when this recovery branch was created. Its previously reported 92-test result and 62 new tests were **not independently reproduced**.

## Evidence / screens
* **No scoring screen run**: this PR wires already-merged engines; it does not create, rescore, or promote a model version.
* **Nine synthetic pytest tests authored**, including real-engine research calls and card parity. Execution and full-suite pass counts are **NOT YET VERIFIED**; use exact hosted CI and Rocky's independent reproduction before merge.
* No real timestamped DK captures or prospective outcomes are claimed by this build.
* No changes to registration, PLAY status, thresholds, frozen NBA props preregistration/evaluator, or the specified holds.

## File identity (Git blobs, not SHA-256)
* `artifacts/run_it_full.py`: `a5799b6ffae10215b8ee09c084b26d60f35f2ded`
* `sportsedge/research/nfl_nba_engine_card_annex.py`: `38fd57f086e51fef571713fb5bf56657891c5ab1`
* `tests/test_nfl_nba_research_annex.py`: `735967106bbb6969221d83d6521a89916b70a107`

## Remains unproven
* Hosted CI and independent test reproduction on the **exact PR head**.
* Real-world supported event-ID/player-ID schema parity with the official DraftKings captures and intake. An unbound field refuses rather than guessing.
* Source independence for operator-supplied pins, correctness/completeness of histories, and NBA period-fit archival provenance.
* Regression byte-parity on the supported full phone-card corpus; the synthetic parity test is not a substitute.
* No eligibility release or production rollout authorized.
