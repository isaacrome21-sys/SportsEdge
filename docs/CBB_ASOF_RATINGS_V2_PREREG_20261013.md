# Pre-registration: CBB as-of ratings v2 (joint home court + non-D1 handling)

Committed before v2 code was run on data. **Governance flag:** this is a new pre-registration path and needs ChatGPT freeze-inventory registration. Research only. Lines are NAIVE_STANDIN; market baseline MISSING. The Illinois ID exclusion is unchanged.

## Why
In v1 (`CBB_ASOF_RATINGS_RESULT_20261013.md`, FAIL) the home-court estimate was the raw mean home margin, about 10 points. It was confounded by strength mismatches.

## Changes (fixed)
1. **Joint home court.** In each of the 20 opponent-adjustment iterations, recompute
   H = mean over trainable non-neutral games of [(home pts − away pts) − pace·((O_h + D_a) − (O_a + D_h))/100],
   i.e. the home residual after current team strengths. Efficiency rows are re-de-biased by ±H/2 with the current H. H starts at 0.
2. **Non-D1 opponents.** Teams not in the ESPN D1 directory (`teams?groups=50`, identity only, captured 2026-10-13) are pooled into one shared `NON_D1` pseudo-team rating, shrunk like any team. Games involving a non-D1 team are used in training but **excluded from evaluation**.

## Unchanged from v1
- Data and cache, PIT rule (completed and start + 3h ≤ cutoff), possessions formula.
- Shrink (5 pseudo-games), 20 iterations, residual-SD Normal.
- Stand-in line definitions (spread now uses the joint H), naive baselines, metrics.
- Illinois exclusion by ESPN id.

## Decision rule (fixed)
- PASS_RESEARCH iff model Brier < naive for moneyline, spread and total, and moneyline log-loss < naive.
- Otherwise FAIL. Reported alongside v1. No tuning.
- Note: because non-D1 games are dropped, the v2 evaluation population is a subset of v1's. v1 is re-scored on the same subset for comparison.
