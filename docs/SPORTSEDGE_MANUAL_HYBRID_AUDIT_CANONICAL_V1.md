# SportsEdge Manual + Hybrid Audit Canonical V1

Status: **architecture/governance contract; not a profitability or certification claim.**

This document resolves wording drift between prior narrative blueprints. The machine-readable files named below are authoritative. If prose conflicts with a named config, the config controls. Any config change requires a new version/hash and affected replay.

## Shared invariants

- MANUAL and HYBRID are acquisition/execution modes of the same sport model, not different predictive models.
- Identical normalized PIT features + model artifacts + seed policy + quotes must produce identical Model_P, distribution, edge and EV.
- Sportsbook lines, implied/no-vig probability, public splits, steam and analyst opinion are forbidden from Model_P.
- Narrative overrides may BLOCK, DOWNGRADE or NO_CHANGE only. They cannot rewrite Model_P.
- Binary de-vig requires an exact compatible two-sided pair under the frozen benchmark/quote policy.
- Every decision must link a content-addressed decision provenance record containing MODEL_CODE_SHA, MODEL_ARTIFACT_SHA, FEATURE_SCHEMA_VERSION/SHA, CALIBRATOR_SHA, SIMULATION_ARTIFACT_SHA, SEED_POLICY, POLICY_SHA, BENCHMARK_METHODOLOGY_SHA, EVIDENCE_GATE_SHA and DATA_CUTOFF.

## CFB canonical policy

Authoritative files:

- `config/cfb_truth_gate_v1.json`
- `config/cfb_validation_policy_v1.json`
- `config/cfb_quote_sync_v1.json`
- `config/cfb_market_benchmark_v1.json`
- `config/manual_hybrid_governance_v1.json`

Resolved numeric execution/validation values:

- Live edge floor: **3.0%**.
- Pregame live quote maximum age: **180 seconds**.
- Maximum two-sided pair timestamp skew: **30 seconds**.
- CFB spread key-number mass absolute tolerance at -7/-3/+3/+7: **0.015 (1.5 percentage points)** per outer fold.
- Overall ECE hard maximum: **0.025**.
- Previously discussed actionable-edge ECE 0.035 is retained as a **segmented diagnostic only**, not a second hidden promotion threshold and not a weakening of the 0.025 overall hard gate.
- Minimum Monte Carlo paths: **10,000**, with standard error no greater than **20% of the live edge floor**; increase paths until this precision contract passes.

CFB main markets remain MONEYLINE / SPREAD / TOTAL and are independently certified. CFB props remain separate.

## Push probability basis

For a push-capable spread/total wager:

`Model_P_nonpush = P_WIN / (1 - P_PUSH)`

EDGE compares that value with the paired sportsbook **no-vig probability on the same non-push basis**.

EV remains unconditional:

`EV = P_WIN * net_win_profit + P_PUSH * 0 - P_LOSS`

Mixing conditioned and unconditioned probability bases is forbidden.

## MLB canonical policy

Authoritative files:

- `config/mlb_truth_gate_v1.json`
- `config/mlb_validation_policy_v1.json`
- `config/mlb_market_benchmark_v1.json`
- `config/manual_hybrid_evidence_gate_v1.json`

MLB_TRUTH_GATE_V1 numeric hard gates include:

- PIT reproducibility required; leakage violations = **0**.
- Minimum forward seasons: **3**; target **5**.
- Model Brier and log loss must beat the frozen no-vig market benchmark.
- Minimum season-fold scoring win rate: **0.60**.
- Mean no-vig CLV: **>= 0.004**.
- CLV t-stat: **>= 2.0**.
- ROI after vig: **strictly > 0**.
- Calibration slope: **0.90-1.10**.
- Absolute calibration intercept: **<= 0.03**.
- ECE: **<= 0.025**.
- Minimum promoted sample: **200**; preferred **600**.
- Live edge floor: **2.5%**.
- Fresh two-sided quote, exposure limits, coherent joint constraints, model-code SHA, feature-schema SHA and structural-change clearance required.

MLB market families are independent. Engine existence does not imply OFFICIAL.

MLB benchmark initial frozen quote rules use a maximum age of **180 seconds** and maximum two-sided pair skew of **30 seconds**. Provider hierarchy and fallback are deterministic in `config/mlb_market_benchmark_v1.json`.

MLB distribution validation requires outer-fold mass checks for total runs 7/8/9 and game margins -1/+1, with pre-registered absolute mass tolerance **0.015**. This threshold is a pre-replay governance choice, not a claim that it is empirically optimal.

## Structural-break revocation

A material scoring/rules/overtime/roster-regime/schedule-format/market-settlement/material-data-definition change can revoke OFFICIAL immediately, independent of rolling statistics.

`OFFICIAL -> REVOKED`

There is no automatic re-promotion. Re-promotion requires:

1. new model or policy artifact version;
2. new policy-bundle SHA;
3. complete PIT replay under the new regime contract;
4. all sport/market Truth Gate requirements;
5. all required attestations;
6. exclusion of rows declared invalid by the structural break.

The executable lifecycle contract lives in `sportsedge/core/certification_lifecycle.py`.

## MLB evidence invalidation

A newer authoritative starting-pitcher change, confirmed-lineup change for a lineup-dependent engine, or doubleheader/game-identity change invalidates the affected existing Model_P. The next action must be **RECOMPUTE_OR_BLOCK**. Narrative probability adjustment is forbidden.

## Provider degradation

`config/provider_degrade_matrix_v1.json` controls provider failures. Predictive-feature failures block affected model/markets unless an explicit hashed feature-policy fallback exists. Executable/benchmark provider outages may use only the next frozen valid tier. Public-context outages degrade context only and never change Model_P.

## Threshold freeze / holdout discipline

- No Truth Gate threshold may be tuned after final holdout inspection.
- Silent threshold migration is forbidden.
- A threshold/config change creates a new version/hash and requires affected replay.
- The final holdout cannot be used to tune model, prior decay, regularization, calibrator, residual distribution, benchmark methodology or gate threshold.

## Current claim ceiling

This branch does not by itself prove any CFB or MLB market profitable, calibrated or OFFICIAL. Durable PIT replay and attested evidence remain required under the relevant market-specific gate.
