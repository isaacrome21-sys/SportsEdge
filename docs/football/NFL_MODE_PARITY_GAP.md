# NFL Manual / Hybrid / Automatic parity — remediation status

Status: **PARITY SURFACE IMPLEMENTED / PRODUCTION STATE-MACHINE BINDING + EXECUTION EVIDENCE PENDING**

This document records the 2026-08-30 audit-remediation trace. The acceptance standard remains the MLB/CFB standard: mode parity is valid only when real ingress ownership converges on one shared execution boundary. A label alone is not a mode.

## Reusable architecture now present

The NFL M2 predictive core remains unchanged and market-blind. `sportsedge/sports/nfl/m2.py` derives a joint score distribution before sportsbook thresholds are applied, while `sportsedge/sports/nfl/model_artifact.py` binds the production model to exact code/source identity.

The split live path has now been factored into reusable components without changing M2 mathematics:

1. `sportsedge/sports/nfl/live_features.py::build_nfl_live_feature_payload()` is the reusable strictly-as-of feature builder. It consumes frozen schedule/PBP/participation/depth/stadium files, excludes target/in-progress PBP and participation, filters future depth rows, removes market/realized-score fields, binds provider team identities, and emits the same source-manifest/as-of provenance used by the production CLI.
2. `scripts/build_nfl_live_feature_rows.py` is now a thin CLI wrapper over that reusable builder.
3. `sportsedge/sports/nfl/odds_source.py::fetch_nfl_odds()` is the reusable DraftKings/The Odds API acquisition contract with key failover, fixed market coverage, untouched provider payload, and response-shape validation.
4. `scripts/fetch_nfl_forward_odds.py` is now a thin CLI wrapper over the reusable odds source.
5. `sportsedge/sports/nfl/live_runner.py::run_canonical_nfl_live()` is the shared normalized execution boundary: frozen feature payload + frozen odds snapshot + exact M2 model/identity -> game/event binding -> M2 score distribution -> `build_forward_decision_rows(...)` -> source/as-of provenance.
6. `sportsedge/sports/nfl/live_runner.py::run_nfl_live()` owns explicit ingress modes:
   - **MANUAL**: caller supplies frozen feature payload and frozen raw odds snapshot.
   - **HYBRID**: caller supplies frozen feature payload while sportsbook acquisition is delegated to the reusable automatic odds ingress.
   - **AUTOMATIC**: feature construction and sportsbook acquisition are both delegated to reusable automatic ingress callbacks.

All three modes converge on `run_canonical_nfl_live(...)`; execution mode does not select predictive mathematics or downstream economic logic.

## Parity contract now present

`tests/test_nfl_mode_parity.py` now constructs one frozen canonical feature payload, one raw sportsbook snapshot, one exact M2 model/identity, and one capture time, then requires MANUAL/HYBRID/AUTOMATIC outputs to be byte-identical. It also requires the same three market rows, source-manifest hash, feature-as-of timestamp, code SHA, model-artifact SHA, and shadow-only governance state. Separate tests prove the mode ownership requirements fail closed and that a future feature snapshot is rejected in every mode.

`tests/test_nfl_odds_source.py` separately covers the reusable provider URL/market contract, untouched payload behavior, and fail-closed response-shape validation.

This is **implementation/code-inspection evidence only** until a real test runner executes the new tests. GitHub-hosted jobs on this branch continue to terminate before any steps execute, so no passing claim is made.

## Remaining production-binding gap

The scheduled forward-evidence workflow still enters `scripts/update_nfl_forward_state.py::decision_mode()`, whose decision section predates `run_canonical_nfl_live(...)` and currently duplicates the same model/event/distribution/readout operations before persisting durable decisions. The next remediation is to route that state-machine decision path through the canonical runner while preserving its existing idempotency/partial-game guards and its exact error semantics. Until that binding is complete, the new mode surface is reusable and semantically aligned with production, but the scheduled durable-state path has not yet been proven to execute through the same function.

## Acceptance before calling NFL parity closed

Parity closes only when:

- `decision_mode()` delegates new-game pricing to the canonical runner rather than reimplementing the core;
- the production workflow continues to use the factored feature and odds CLI wrappers;
- `tests/test_nfl_mode_parity.py`, `tests/test_nfl_odds_source.py`, existing forward-state tests, and the wider NFL contract suite execute successfully on a real runner;
- no production predictive coefficient, eligibility flag, Truth Gate floor, PIT rule, or promotion requirement is changed by the refactor.

## Governance

This architecture work does **not** install a Truth Gate floor, change deployment eligibility, alter M2 coefficients, loosen PIT chronology, or create predictive/promotion evidence. NFL remains shadow/research only until independent OOS/CLV/calibration/promotion gates are actually satisfied.
