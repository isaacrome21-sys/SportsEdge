# SportsEdge CFB Audit Specification v1.2

Status: **ARCHITECTURE HARDENED / EMPIRICAL CERTIFICATION UNRUN**

This document supersedes CFB audit specification v1.1 implementation ambiguity. It does **not** change the numerical thresholds in `CFB_TRUTH_GATE_V1` and does not claim that any CFB market is empirically certified.

## 1. Canonical architecture

SportsEdge CFB is one model with three execution modes:

`MANUAL -> HYBRID -> AUTOMATIC`

Given identical point-in-time inputs, model artifact, calibrator, simulation seed/policy and policy bundle, the mathematical outputs must be identical. Manual/Hybrid narrative overrides can only block or downgrade a result; they cannot mutate `Model_P`, fair price, edge or EV. Automatic mode cannot apply narrative overrides.

Canonical flow:

`PIT data -> provenance/leakage validation -> market-blind CFB features -> Model_P/joint score distribution -> nested calibration -> market readout -> normalized odds -> benchmark/reference -> edge/EV -> historical/live policy -> audit manifest`

Public betting, sportsbook consensus, opening/closing lines, social posts and handicapper opinions remain downstream market context and never enter predictive `Model_P` or historical certification features.

## 2. Audit findings accepted

### C1 — early-season prior decay

Accepted. Weeks 1-4 use a versioned, monotone prior-decay artifact estimated on training seasons only. The outer held-out season is forbidden from fitting the decay schedule. Each artifact carries `prior_version`, training seasons and a content hash. Prior-vs-no-prior ablation is required by week.

Implementation: `sportsedge/core/prior_decay.py`.

### C2 — source-level PIT leakage

Accepted and strengthened. Promotion-grade feature sources must carry:

- `source_id`
- `source_version`
- `source_asof_ts`
- `feature_asof_ts`
- `ingested_ts`
- `game_start_ts`
- `max_latency_seconds`
- `provenance_id`

Required ordering is `source_asof_ts <= feature_asof_ts < game_start_ts`, with ingestion latency inside the declared source contract. Deliberate post-kick and latency fixtures must fail.

Implementation: `sportsedge/core/leakage.py` and `sportsedge/sports/cfb/audit_contracts.py`.

### C3 — discrete score distribution / key numbers

Accepted with a safeguard: SportsEdge will not hand-add arbitrary probability mass at 3 or 7. The current joint CFB simulator is already integer-valued and uses empirical residual pairs. Before promotion it must reproduce held-out empirical mass at key margins within a frozen tolerance. Only demonstrated out-of-sample bias can justify a learned correction.

Implementation: `sportsedge/sports/cfb/key_number_validation.py`. Existing predictive engine remains `sportsedge/sports/cfb/joint_model.py` until a replacement proves superior out of sample.

### C4 — CLV contract

The audit correctly identified ambiguity but its proposed formula `Model_P - Closing_NoVig_P` is **not** CLV. SportsEdge freezes:

`CLV_prob = Closing_NoVig_P(original contract) - Decision_NoVig_P(original contract)`

Positive means the market subsequently valued the exact wager more highly. `Model_P_at_decision - Closing_NoVig_P(original contract)` is stored separately as `model_vs_close` diagnostic.

For spreads/totals the close must price the original decision threshold. An alternate closing quote may be used; otherwise a frozen repricing method must recreate the original contract. If it cannot be repriced, the row is not CLV-certifiable.

Implementations: `sportsedge/core/clv/football.py`, `sportsedge/sports/cfb/benchmark.py`, `config/cfb_market_benchmark_v1.json`.

### C5 — entity resolution

Accepted. A versioned authoritative SportsEdge entity registry owns canonical team IDs, aliases and FBS/FCS classification. Alias collisions and unresolved identities fail closed; no fuzzy guessing is allowed.

Implementation: `sportsedge/sports/cfb/entity_registry.py`.

### H1 — heteroskedastic variance

Accepted as a candidate, not silently promoted. V1 candidate uses a small regularized feature set: projected total, pace, favorite size, QB uncertainty and explosiveness differential. It is fit on training-only residuals and must beat the unconditional residual baseline out of sample before the joint simulator may adopt it.

Implementation: `sportsedge/sports/cfb/variance.py`.

### H2 — calibration

Accepted and strengthened. Outer held-out seasons remain untouched. Calibration is fit on chronological inner out-of-fold predictions from seasons strictly earlier than the outer test season. Raw, calibrated and benchmark metrics are retained.

Implementation: `sportsedge/sports/cfb/validation_v12.py` plus the existing fold-safe isotonic calibrator.

### H3 — overrides

Accepted. Verified information may change Model_P only when it enters through an approved versioned PIT feature contract. Narrative Manual/Hybrid overrides after prediction may only `BLOCK`, `DOWNGRADE` or `NO_CHANGE`. Automatic narrative overrides are forbidden.

Implementation: `CFBOverride` and `govern_cfb_report`.

### H4 — full-board coverage

Accepted. Every expected in-scope game must be represented exactly once in coverage as `SCORED`, `BLOCKED` or `UNAVAILABLE`. Missing quotes/data are explicit states, not silent drops. 100% accounting is required; 100% successful scoring is not.

Implementation: `CoverageReport` and `build_coverage_report`.

### H5 — historical market benchmark

Accepted. Benchmark selection is deterministic by provider priority tier and timestamp contract. No post-hoc source selection is permitted. The precise quote IDs and fallback tier must be retained.

Implementation: `config/cfb_market_benchmark_v1.json` and `sportsedge/sports/cfb/benchmark.py`.

## 3. Additional audit hardening

### Push semantics

For spread/total markets the simulator emits `P(win)`, `P(push)`, `P(loss)`. EV is unconditional because a push returns stake. Binary sportsbook fair probabilities and probability scoring are evaluated conditional on a non-push outcome; realized pushes are excluded from binary Brier/log-loss and push calibration is reported separately.

### Circular promotion eliminated

`historical_candidate_policy()` applies the frozen edge/EV/data/price rules without requiring prior certification and emits `SHADOW_QUALIFIED` evidence. `live_candidate_decision()` applies the same selection logic plus the requirement that the market is already historically `OFFICIAL`.

Implementation: `sportsedge/sports/cfb/decision_policy.py`.

### Props remain isolated

CFB player props are `EXPERIMENTAL_PROP` / `MANUAL_HYBRID_REVIEW` only. They cannot inherit `CFB_TRUTH_GATE_V1`. A separate prop-specific historical gate is required before official prop execution.

Implementation: `sportsedge/sports/cfb/prop_contract.py`.

## 4. Frozen policy bundle

Live/audit manifests must reference the versioned bundle components:

- spec SHA
- `CFB_TRUTH_GATE_V1` policy SHA
- `CFB_MARKET_BENCHMARK_V1` methodology SHA
- exposure policy SHA
- market-context policy SHA
- prior version + decay schedule hash
- variance model version
- key-number method
- model / feature / calibrator / simulation versions

The exact decision-time quote is immutable.

## 5. Validation protocol

For each main market separately:

1. Season-based outer walk-forward only; never shuffle.
2. Fit model/hyperparameters/prior decay using prior seasons only.
3. Produce inner out-of-fold predictions for calibration.
4. Fit calibrator on those inner OOF predictions only.
5. Score untouched outer season.
6. Report raw, calibrated and frozen benchmark Brier/log-loss.
7. Report calibration slope, intercept and ECE.
8. Report key-number calibration for spread distributions.
9. Report by weeks 1-4/5+, conference-strength bucket and favorite-size bucket.
10. Report feature/prior ablations and coefficient sign/magnitude stability.
11. Apply frozen historical candidate policy to form the promotion sample.
12. Score original-contract no-vig CLV, ROI after vig and rejected-play CLV diagnostics.
13. Replay `CFB_TRUTH_GATE_V1` per market.

No pooled-only result can promote a market.

## 6. Current certification state

The branch adds enforceable architecture and tests. It does not create missing historical evidence.

Unless a replayable evidence artifact proves otherwise:

- CFB Moneyline: **NOT CERTIFIED**
- CFB Spread: **NOT CERTIFIED**
- CFB Total: **NOT CERTIFIED**
- CFB Props: **EXPERIMENTAL**
- Historical Truth Gate replay: **UNRUN under v1.2**
- Live official execution: **BLOCKED until the relevant market passes historical certification**

Zero official bets is a valid outcome. Thresholds may not be weakened to force action.
