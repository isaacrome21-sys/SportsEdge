# SportsEdge MLB Statcast V5 — untouched 2025 holdout result

Source workflow run: `31627930135`
Source commit: `0571a3b0d0d063279840735f88230e9112bed07a`
Predeclared protocol: `audit/STATCAST_V5_PREDECLARED_PROTOCOL_2026-08-12.md`

This file records results after the frozen protocol was committed. It does not alter any threshold, split, feature contract, or model-selection rule.

## Frozen artifacts

- Contact transformer SHA-256: `bf61487279ac9a506318e9dfa078a866450dd4e363b1d06356e58852954133b2`
- GAME_SCORE_V5_STATCAST SHA-256: `d467b1221898fdb84562ea2b72a06287bfae3e58603e3b15a28fba40c9cc668e`
- NRFI_V5_STATCAST SHA-256: `a12881071bb53a52c6dcfaaacbf6e7c844e329beb7bb2df204124c064d4b21cc`
- Contact-transformer training BBE: 231,703
- Valid untouched-2025 game rows: 1,870
- Valid untouched-2025 first-inning rows: 1,870

## GAME markets

MONEYLINE: PASS. Home-ML aggregate calibration z = 1.5997562438904471, below the frozen 2.5 limit.

RUN_LINE: PASS. Every evaluated aggregate bucket is below 2.5. Observed z values: +1.5 = 1.0149398290089986; +2.5 = 1.1750456092721284; -1.5 = 0.061186145954736995; -2.5 = 0.20884252065388745.

TOTALS: PASS. Every evaluated aggregate bucket is below 2.5. Observed z values: O7.5 = 1.2391929982832885; O8.5 = 0.5187536644538558; O9.5 = 0.8132860490599858; O10.5 = 0.22197900372611568.

These holdout passes advance GAME V5 only to live-parity/runtime-attestation work. They do not by themselves authorize deployment.

## First-inning markets

NRFI: FAIL.
YRFI: FAIL.

Overall first-inning calibration z = 2.5616523851699866, exceeding the frozen 2.5 limit. The populated 0.4-0.6 probability bucket has the same z = 2.5616523851699866 and is below the separate 3.0 bucket limit, but the overall 2.5 gate controls and therefore fails.

No threshold is widened, no 2025-driven retuning is permitted under this protocol, and NRFI/YRFI V5 remain blocked.

## CI artifact verification

The workflow recomputed SHA-256 after fitting and verified the emitted contact transformer, GAME V5 artifact, NRFI V5 artifact, and validation record before uploading the evidence bundle. The workflow concluded failure solely because the predeclared NRFI/YRFI holdout gate failed.
