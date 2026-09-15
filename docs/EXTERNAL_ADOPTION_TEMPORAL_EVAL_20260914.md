# Temporal evaluation engineering adoption — 2026-09-14

Status: RESEARCH / ENGINEERING REFERENCE ONLY. No Model_P, validation-attempt, Truth Gate, promotion, staking, eligibility, edge-floor, or OFFICIAL authority.

## Source

- Repository: `dk3yyyy/football_predictor`
- Immutable commit: `7551c515f29d94ddd958da483c1178f468b90b81`
- License at that commit: MIT (`LICENSE` blob `47f3932b9907fe09c39c7f8441d29451c9a079ec`)

## Patterns adopted

SportsEdge independently implements only these engineering ideas:

1. chronological, non-overlapping train → calibration → untouched-test windows;
2. deterministic evaluation identity bound to the actual rows used;
3. explicit provenance separation between evaluation partitions;
4. fail-closed rejection rather than shuffling or silently assigning rows that fall into undeclared temporal gaps.

SportsEdge additionally requires event/game identity disjointness across partitions and exposes deterministic event clusters so repeated snapshots from one game can be treated as one sampling unit by later cluster-aware uncertainty code.

## Explicitly not adopted

No source probabilities, trained models, coefficients, feature values, claimed accuracy, Brier/log-loss results, bookmaker comparisons, or performance evidence are imported. No market-derived field becomes a SportsEdge predictive feature. This adoption cannot satisfy any SportsEdge evidence threshold by itself.
