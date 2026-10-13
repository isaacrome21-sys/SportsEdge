# Pre-registration: NBA quarter sim, separating the V2 confound. (a) Frozen calibration alone; (b) overtime-frequency fix

This doc was committed **before** any code for (a) or (b) was written or run.

**Governance flag:** this is a new pre-registration path and needs ChatGPT freeze-inventory registration. It is research only. Lines are naive stand-ins, the market baseline is MISSING, and rest_adj = 0.

## Disclosure
- V1 and V2 results on 2025-26 are already known (`NBA_QUARTER_SIM_REG_SHARE_V2_RESULT_20261013.md`): V2 is PASS_RESEARCH by rule, but the regulation-share fix and the calibration freeze were confounded.
- Known diagnostics: on 2025-26, the sim OT rate is 2.2% vs 4.5% actual.
- Hypothesis (from code, not tuned on 2025-26): V1's per-quarter `resid_sd` is measured around the **league** mean, so it includes between-team strength variance. That over-disperses the simulated margin, which in turn under-produces regulation ties.

## Arms (all on the 2025-26 holdout, identical games, ratings, seeds, n_paths = 3000, naive lines)
- **V1:** unchanged (in-season cold calibration, V1 `simulate`).
- **(a) FROZEN_CAL:** V1 `simulate` (the V1 reg_share scaling, *no* moment match), with calibration frozen from all 2024-25 quarter games, as in V2. This isolates the freeze.
- **(b) OT_FIX:** V1 in-season calibration and V1 `simulate`, plus a **margin-dispersion factor `c`** applied to regulation quarters only.
  - Per quarter and path: `m = (h − a)/2`, `s = (h + a)/2`, then `m' = E[m] + c·(m − E[m])`, then `h = s + m'`, `a = s − m'`, rounded and floored at 0.
  - This leaves totals unchanged in expectation and changes only margin spread, and therefore the regulation tie rate.
  - **`c` is calibrated only on 2024-25.** Run the V1 walk-forward (cold in-season calibration and ratings, exactly as the V1 harness) on 2024-25, scoring games with ≥ 10 games per team.
  - Choose `c` from the grid {0.60, 0.62, …, 1.00} minimizing |mean sim regulation-tie rate − actual 2024-25 regulation-tie rate|; ties go to the larger `c`.
  - `c` is then frozen for 2025-26.

## Metrics
TOTAL, H1, Q1 and ML Brier and log-loss, mean (sim − actual) total, and sim OT rate vs actual OT rate.

## Decision (fixed, each arm vs V1 independently)
- **(a) PASS_RESEARCH** iff Brier < V1 **and** log-loss < V1 on ≥ 2 of {TOTAL, H1, Q1}, and no Brier regression > 0.002 on any of the three.
- **(b) PASS_RESEARCH** iff all of the following hold:
  - the 2025-26 sim OT rate is within **1.0 percentage point** of the actual 2025-26 OT rate;
  - ML Brier ≤ V1 ML Brier + 0.001;
  - no Brier regression > 0.002 on TOTAL, H1 or Q1.
- Otherwise each arm is FAIL. The result is reported in full regardless of outcome. There is no promotion.
