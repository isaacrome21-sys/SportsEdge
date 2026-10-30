# Result: CBB as-of ratings v2 walk-forward (2024-25) — PASS_RESEARCH

Pre-registration: `CBB_ASOF_RATINGS_V2_PREREG_20261013.md`, committed in 0005cdf before the run. Research only. Lines are NAIVE_STANDIN, not market. **Market baseline MISSING.** No PLAY output.

Population: 4,387 D1-vs-D1 scored games (4,384 for totals after pushes). Excluded: 524 games with a non-D1 team and 378 Illinois games (by ESPN ID; used in training only). v1 was re-scored on the same subset.

| market | n | v2 Brier | v1 Brier (same subset) | naive Brier | v2 log-loss | naive log-loss |
|---|---|---|---|---|---|---|
| moneyline | 4387 | **0.1941** | 0.2290 | 0.2470 | **0.5675** | 0.6928 |
| spread (stand-in) | 4387 | **0.2384** | 0.2513 | 0.2500 | 0.6693 | 0.6931 |
| total (stand-in) | 4384 | **0.2443** | 0.2449 | 0.2500 | 0.6818 | 0.6931 |

Joint home court at the end of the season: **H = 4.69** (v1 raw = 8.94).

**Decision: PASS_RESEARCH.** v2 beats naive on all three Brier scores and on moneyline log-loss.

## Caveats
- **Weak stand-in lines.** Spread and total are measured against naive stand-in lines, not market lines. A real edge is unproven until paired, timestamped closing odds exist.
- **Home court may still be high.** H ≈ 4.7 is above the usual ~3–3.5. Some schedule confounding probably remains.
- **D1 directory look-ahead.** D1 membership comes from the ESPN directory as captured 2026-10-13. This is identity only, not outcomes, but there is a small look-ahead risk from conference and division moves.
- **No tuning, one season.** There was no tuning, and this is a single season. v1 remains FAIL as recorded.

## Additional caveats (ChatGPT review)
- **Stand-in lines.** Spread and total lines are NAIVE_STANDIN constructions, not market lines. PASS_RESEARCH here is not evidence of an edge against DK.
- **2026 directory.** Historical D1/non-D1 membership comes from the ESPN team directory as captured in 2026, not from a 2024-25 as-of directory.
- **Season already examined.** The 2024-25 season was already examined during v1. v2 was designed after seeing v1's failure, so it is not fresh out-of-sample evidence. A clean confirmation needs an unexamined season.
- **Governance flag.** `CBB_ASOF_RATINGS_V2_PREREG_20261013.md` fails the freeze-inventory check. It is left unrenamed for ChatGPT to register.
