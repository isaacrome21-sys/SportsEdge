# NFL Manual / Hybrid / Automatic parity — architecture gap

Status: **IMPLEMENTATION GAP — parity test intentionally not fabricated**

This document records the repo trace performed during the 2026-08-30 audit remediation. The acceptance standard is the same one used for MLB and CFB: a mode-parity test is valid only when the compared modes are real production ingress paths that normalize into one shared execution boundary. A label or test-only wrapper is not a mode.

## What exists today

The NFL M2 predictive core is real and market-blind. `sportsedge/sports/nfl/m2.py` builds the score distribution before sportsbook lines are applied. The model artifact contract in `sportsedge/sports/nfl/model_artifact.py` binds the production model to exact code/source identity.

The current live/forward path is split across workflow and script boundaries:

1. `.github/workflows/football-nfl-forward-clv-collection.yml` freezes the schedule and strictly-prior public feature sources, resolves an exact production model release, builds live features, fetches DraftKings odds, and then invokes the durable forward-state script.
2. `scripts/build_nfl_live_feature_rows.py` builds strictly-as-of, market-blind live M2 feature payloads from frozen schedule/PBP/participation/depth/stadium files.
3. `scripts/fetch_nfl_forward_odds.py` acquires raw DraftKings h2h/spread/total provider snapshots.
4. `scripts/update_nfl_forward_state.py::decision_mode()` loads the exact model artifact, validates live-feature chronology/source identity, binds the provider event to the NFL game, derives the M2 joint score distribution, and calls `build_forward_decision_rows(...)`.
5. `sportsedge/core/clv/nfl_forward_capture.py::build_forward_decision_rows()` is the existing pure downstream game-market pricing/economics surface for moneyline, spread, and total.

This is a legitimate AUTOMATIC scheduled forward-evidence path, but acquisition ownership is distributed across Actions shell steps and CLI scripts rather than one reusable NFL run-machine API.

## What does not exist

At this branch head there is no `sportsedge/sports/nfl/run_machine.py` and no NFL source/ingress module analogous to CFB's `run_machine.py` + `source.py`.

More importantly, there are not yet three independently real NFL ingress contracts that can be truthfully named MANUAL, HYBRID, and AUTOMATIC and then compared byte-for-byte. The repository contains an automatic scheduled path and reusable predictive/downstream primitives, but it does not contain a canonical manual path plus a genuinely distinct partial-acquisition hybrid path converging on one explicit shared-core boundary.

Therefore an NFL parity test written now by merely passing the same objects through three labels would be false evidence and is prohibited.

## Required remediation before a parity claim

The next implementation step is to factor the existing live path without changing predictive mathematics:

- expose the strictly-as-of live feature builder as a reusable library function while preserving the current CLI as a thin wrapper;
- expose NFL odds acquisition/normalization as a reusable ingress function while preserving secret-safe key handling;
- define one canonical normalized NFL game-market execution function that owns artifact validation, game/event binding, M2 distribution construction, paired-price/no-vig economics, and output provenance;
- wire real ingress ownership around that boundary:
  - **MANUAL**: caller supplies the frozen normalized live feature payload and frozen odds snapshot;
  - **HYBRID**: caller supplies one execution-sensitive frozen input while the other is acquired/built through the real reusable production ingress; which input is manual must be explicit in the contract, not inferred from a label;
  - **AUTOMATIC**: both live feature payload and odds snapshot are produced through the real production acquisition/build path;
- keep exact model-artifact identity, code/source hashes, feature as-of time, capture time, game/event identity, paired prices, and policy settings identical in the parity fixture.

Only after those paths exist should `tests/test_nfl_mode_parity.py` assert the same post-normalization acceptance surface used elsewhere: canonical game/input object, normalized paired quotes, feature payload, timestamps, artifact/code/source identity, policy/Kelly settings, then exact downstream Model_P/readout/economic/status/provenance fields.

## Governance

This architecture work does **not** install a Truth Gate floor, change deployment eligibility, alter M2 coefficients, loosen PIT chronology, or create promotion evidence. The checked-in football implementation status already distinguishes PRESENT from EXECUTED from EVIDENCE-PRODUCING; this parity gap remains an execution/orchestration problem until the real ingress paths are factored and behaviorally executed.
