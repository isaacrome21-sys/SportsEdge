# MLB batter & pitcher prop held-out calibration

## Status
Engines already ship:
- Hitter: `sportsedge/hitter_joint_engine.py` (EB joint history rows)
- Pitcher: `sportsedge/pitcher_joint_engine.py` (EB joint start rows)

This track is **calibration / promotion evidence**, not a new simulator.

## Evidence primitives
- `sportsedge/mlb_prop_forward_evidence.py` — prospective receipts only; no Model_P authority
- `scripts/capture_mlb_prop_forward_evidence.py` — StatsAPI capture

## Gate
Per market family (hitter primary markets first, then pitcher):
1. Held-out graded window with pregame feature identity bound before first pitch.
2. Non-inferior (or better) Brier vs a frozen baseline snapshot of the same engine version.
3. No silent support violations (line outside feasible settlement range).
4. Promote only via explicit PR; do not auto-promote from this research branch.

## Order
1. Batter: HITS, HOME_RUNS, TOTAL_BASES, BATTER_K, BATTER_BB
2. Pitcher: PITCHER_K, PITCHER_HITS_ALLOWED, PITCHER_BB, PITCHER_OUTS
3. Combos / either-pitcher only after singles pass

## Explicit non-goals
- Changing joint engines without a failed held-out gate
- Mixing prop results into moneyline v2 clocks
