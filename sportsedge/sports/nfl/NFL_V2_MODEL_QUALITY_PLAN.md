# NFL V2 model-quality workstream

Tracking issue: #379

This branch exists to improve the NFL score-distribution/model quality **without changing frozen promotion gates**.

## Frozen constraints

- Keep NFL M2 market-blind. No spread, total, moneyline, public betting, or sportsbook price may become a model feature.
- Preserve PIT/walk-forward ordering and held-out season isolation.
- Preserve exact code SHA, source-manifest, model-artifact, and byte-determinism binding.
- Do not relax the existing 0.65 fold-win requirement, calibration threshold, key-number tolerance, CLV requirements, eligibility rules, or Truth Gate.
- Candidate results remain diagnostic until they independently pass the full frozen chain.

## Current evidence baseline

Evidence run 609 at `b907deafad05e9e2b1b8d81f6bd1321d622ff7c3`:

- Production M2 spread: calibration PASS; fold win rate 2/4 = 0.50 -> FAIL.
- Production M2 total: calibration PASS; fold win rate 0/4 = 0.00 -> FAIL.
- Production M2 signed key-number math at +/-3 and +/-7: FAIL.
- V2A improves emergent key-number mass but still fails -3 tolerance and predictive promotion gate.
- Nested V2A and V2B also remain non-promotable.

## Required acceptance test for any replacement candidate

A candidate is not promotion-ready unless the unchanged evidence pipeline proves all of the following at the same exact source/code identity:

1. Deterministic model artifact and validation outputs.
2. PIT-safe multi-season walk-forward predictions.
3. Calibration pass for each proposed promoted market.
4. Fold win rate >= 0.65 for each proposed promoted market.
5. Existing emergent key-number validation passes without hand-injected key weights.
6. Subsequent real forward CLV evidence meets the frozen deployment gate.

Until then, registry eligibility must stay false and RUN IT must not claim OFFICIAL status.
