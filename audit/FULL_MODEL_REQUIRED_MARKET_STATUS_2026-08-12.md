# SportsEdge MLB required-market readiness — 2026-08-12

This snapshot applies the current strict standard for `RUN THE FULL MODEL`.
A family must appear as `PRICED_CANDIDATE`, `NO_PRICE`, `MODEL_NOT_ELIGIBLE`, or `BLOCKED`; silent omission is not allowed. A legacy deployment cannot override a newer stricter validation registry.

## Current market truth

| Family | Current state | Exact reason | Evidence required to unblock |
|---|---|---|---|
| MONEYLINE | MODEL_NOT_ELIGIBLE | Statcast V5 untouched-2025 holdout passed, but exact live Statcast parity and runtime attestation are still required. | Green V5 GAME promotion from the frozen pipeline; exact transformer/game/base-state hashes; live feature parity; live-slate runtime attestation proving the same Statcast feature contract; deployment registry promotion. |
| RUN_LINE | MODEL_NOT_ELIGIBLE | Same GAME_SCORE_V5_STATCAST artifact passed the frozen 2025 RL gates, but live parity/runtime attestation are still missing. | Same evidence chain as ML, including run-distribution parity at runtime and commit-bound artifact hashes. |
| TOTALS | MODEL_NOT_ELIGIBLE | Same GAME_SCORE_V5_STATCAST artifact passed the frozen 2025 totals gates, but live parity/runtime attestation are still missing. | Same evidence chain as ML, including total-distribution parity at runtime and commit-bound artifact hashes. |
| NRFI | MODEL_NOT_ELIGIBLE | Statcast V5 untouched-2025 overall calibration z=2.5616523851699866 exceeded the frozen 2.5 gate. | A separately predeclared new NRFI model/version trained without using the failed 2025 holdout for tuning, followed by a new untouched holdout, exact artifact hashes, live parity, runtime attestation, and registry promotion. Do not change the old threshold. |
| YRFI | MODEL_NOT_ELIGIBLE | Same failed Statcast V5 first-inning calibration gate as NRFI. | Same new-version evidence chain as NRFI. |
| HITS | MODEL_NOT_ELIGIBLE | Production logic exists, but fixture-backed CI attestation is pending. Latest generic attestation stopped at canonical-fixture verification before scoring. | Exact canonical fixture at `fixtures/hits/bb_hits_data.pkl`, 19,948,081 bytes, SHA-256 `aaa006155de8078057fae0bd764a6aebca7e06057d9e83669d816536c5471776`; authoritative full holdout; exact-commit CI attestation; deployment registry promotion. If the current standard requires Statcast for hitter models too, that must be a separately validated hitter version rather than relabeling the legacy artifact. |
| TOTAL_BASES | MODEL_NOT_ELIGIBLE | Production logic exists, but fixture-backed CI attestation is pending. Latest generic attestation stopped at canonical-fixture verification before scoring. | Exact canonical fixture at `fixtures/total_bases/tb_gameeffect_data.pkl`, 24,223,755 bytes, SHA-256 `1a816f5f46bf1042c2dcc13078092b6205b359a2ad49dca3fcfdb7b787914859`; authoritative full holdout; exact-commit CI attestation; deployment registry promotion. If the current standard requires Statcast for hitter models too, use a separately validated hitter version. |
| PITCHER_BB | MODEL_NOT_ELIGIBLE | Current registry remains `VALIDATED_MATH` / production residual gap unresolved. Latest BB-v5 CI failed during the predeclared build with `BB_V5_NON_MONOTONE_SLOPE`; no validation artifact was emitted. | A predeclared BB model version that fits without violating its frozen monotonicity/functional-form rules; development validation artifact; required forward-shadow gate; production-parity/live runtime evidence; exact artifact hash; registry promotion. Do not coerce the slope or loosen the rule after seeing the failure. |

## Pricing-state rule

Price availability is evaluated only after model eligibility. A sportsbook quote cannot promote an ineligible model. For an eligible family:

- no legitimate fresh reachable quote -> `NO_PRICE`;
- runtime identity/lineup/starter/game-state/feature blocker -> `BLOCKED` with exact reason;
- eligible model + legitimate fresh quote + no runtime blocker -> `PRICED_CANDIDATE` (still subject to per-candidate edge/EV and Truth Gate checks).

Sportsbook implied probability/odds must never enter `Model_P`; they are used only for pricing, break-even probability, edge/EV and execution.
