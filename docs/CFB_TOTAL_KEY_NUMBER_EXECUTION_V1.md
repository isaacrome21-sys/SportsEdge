# SportsEdge CFB Total Key-Number Execution Layer v1

Status: `EXTERNAL_REFERENCE_ONLY`, `model_p=false`, `promotion_eligible=false`.

## Source basis
This v1 reference set reproduces the key-total tiers shown in a user-provided Todd Fuhrman X post dated 2026-09-05. The post states:
- top 5 totals: approximately 15%
- top 10 totals: approximately 27%
- top 15 totals: approximately 36%

Published tiers:
- Tier 1 — CRITICAL: 55, 48, 58, 44, 51
- Tier 2 — HIGH: 41, 45, 65, 59, 52
- Tier 3 — ELEVATED: 62, 69, 37, 47, 49
- Tier 4 — MODERATE: 61, 38, 66, 54, 63, 57, 34, 56, 43, 40

SportsEdge does **not** claim these percentages or tiers are independently re-derived or empirically validated by SportsEdge. Until a declared historical dataset, derivation method, sample counts, and OOS check exist, the set remains an external execution reference only.

## Purpose
Use key totals to improve **price and timing discipline** around totals that already have a directional edge from a legitimate SportsEdge model or approved non-Model_P research workflow.

Examples:
- An Under 51.5 candidate may be more urgent than the same Under at 53.5 if waiting risks losing 51.
- An Over 50.5 candidate may be materially preferable to Over 51.5 because 51 is a Tier-1 key total.
- A market move that crosses one or more high-priority totals is logged as execution-relevant movement.

## Prohibited uses
Key totals must never:
- generate an Over/Under direction;
- manufacture `Model_P`;
- turn a PASS into a bet;
- create a confidence vote;
- independently promote a wager;
- be described as a SportsEdge empirical distribution until SportsEdge independently re-derives and validates it.

## RUN IT fields
For a serious CFB total candidate, surface when useful:

`CURRENT_TOTAL | NEAREST_KEY | DISTANCE | KEY_TIER | CROSSED_KEYS | MODEL_P=false`

The total-key layer belongs to **MARKET EXECUTION / KEY-NUMBER CONTEXT**, downstream of the predictive model and upstream of final price/playable-to decisions.

## Implementation
`sportsedge/sports/cfb/total_key_numbers.py`

The module preserves the source tier ordering, finds the nearest key total, detects key totals crossed by market movement, and emits a compact context-only execution payload.
