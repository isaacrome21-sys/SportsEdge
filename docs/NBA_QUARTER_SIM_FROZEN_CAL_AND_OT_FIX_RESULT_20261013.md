# Result: NBA quarter sim split test. (a) FROZEN_CAL PASS_RESEARCH; (b) OT_FIX FAIL

**Provenance**
- Pre-registration: `NBA_QUARTER_SIM_FROZEN_CAL_AND_OT_FIX_PREREG_20261013.md` (`dbe2b36`), committed before the code.
- Code: `f0f2fe3`, committed before the run, and unchanged afterward.
- Command: `PYTHONPATH=. python scripts/run_nba_quarter_sim_split_holdout.py --fit-cache /workspace/nba_cache_q --holdout-cache /workspace/nba_cache_q_2025_26`.
- The 2025-26 holdout has n = 1076, with an actual OT rate of 4.46%.

**Calibrating `c` on the 2024-25 walk-forward** (n = 1076, actual OT rate 4.55%)
- The simulated OT rate rises monotonically as `c` falls: 2.21% at c = 1.00 and only 3.30% at c = 0.60.
- The grid never reached the target, so the pre-registered rule selected the **boundary, c = 0.60**.

| arm | TOTAL Brier / LL | H1 Brier / LL | Q1 Brier / LL | ML Brier / LL | sim − actual total | sim OT rate |
|---|---|---|---|---|---|---|
| V1 | **0.2293** / **0.6511** | 0.2405 / 0.6740 | 0.2458 / 0.6848 | 0.2084 / 0.6060 | +0.41 | 2.17% |
| (a) FROZEN_CAL | 0.2298 / 0.6522 | **0.2402 / 0.6733** | **0.2447 / 0.6824** | 0.2084 / 0.6061 | +0.64 | 2.16% |
| (b) OT_FIX (c = 0.60) | 0.2297 / 0.6519 | 0.2406 / 0.6741 | 0.2458 / 0.6847 | **0.2037 / 0.5959** | +0.66 | 3.23% |

## Decisions (by the pre-registered rules)
- **(a) FROZEN_CAL: PASS_RESEARCH.**
  - It wins H1 and Q1 on both Brier and log-loss.
  - Its worst Brier regression is +0.0005 (TOTAL).
  - This confirms that the H1/Q1 gain in V2 came from freezing the calibration, not from the regulation-share fix.
  - Full-game TOTAL is slightly worse in every non-V1 arm.
- **(b) OT_FIX: FAIL.**
  - The simulated OT rate is 3.23% vs 4.46% actual, a gap of 1.23 pp, which is over the 1.0 pp limit.
  - ML and TOTAL/H1/Q1 met their conditions.

## Honest reading
- **Margin over-dispersion is only part of the OT deficit.** Even at the smallest margin spread on the grid, the sim makes about 30% too few ties.
  - The remainder is likely structural. Each quarter is rounded independently from a continuous Normal, and the model has no end-of-game dynamics (e.g. fouling or score-tied play). That cause is not tested here.
- **The ML improvement for (b) is notable but unplanned.** ML Brier improved 0.2084 → 0.2037, and log-loss 0.606 → 0.596.
  - It is consistent with the sim's margin being too dispersed, so its win probabilities were too timid.
  - ML was *not* a gating success criterion, and `c` sits on the grid boundary. Any claim needs a new pre-registration, with an extended grid fit on 2024-25 only and a fresh holdout. Since 2025-26 has now been examined, that holdout must be 2026-27.
  - **This is not claimed as a result.**
- The game-level ML/spread/total harness, which uses its Normal approximation rather than the sim, is unchanged by this test.
- Research only, with no promotion. The market baseline stays MISSING, and rest_adj = 0.
