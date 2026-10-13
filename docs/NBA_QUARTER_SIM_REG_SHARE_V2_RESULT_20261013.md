# Result: NBA quarter sim V2 regulation-share fix: PASS_RESEARCH (by the pre-registered rule, with caveats)

- **Pre-registration:** `NBA_QUARTER_SIM_REG_SHARE_V2_PREREG_20261013.md` (`b794d35`), committed before any V2 code.
- **Code:** `2b819c4`, committed before the run, and unchanged afterward.
- **Command:** `PYTHONPATH=. python scripts/run_nba_quarter_sim_v2_holdout.py --fit-cache /workspace/nba_cache_q --holdout-cache /workspace/nba_cache_q_2025_26`
- **Fit and holdout:** the frozen calibration was fit on 1,231 games from 2024-25 (reg_share 0.9950, OT 11.0 ± 3.7 points per team). The holdout is 2025-26, n = 1076.

| market (naive stand-in line) | V1 Brier | V2 Brier | V1 log-loss | V2 log-loss |
|---|---|---|---|---|
| full-game TOTAL | **0.2293** | 0.2306 | **0.6511** | 0.6538 |
| H1 total | 0.2405 | **0.2398** | 0.6740 | **0.6724** |
| Q1 total | 0.2458 | **0.2445** | 0.6848 | **0.6821** |
| ML (sim, not gating) | 0.2084 | 0.2084 | 0.6060 | 0.6060 |

**Diagnostics** (not gating):

| | V1 | V2 |
|---|---|---|
| mean sim − actual total | +0.41 | **+1.30** |
| sim OT rate | 2.2% | 2.2% |
| actual OT rate | 4.5% | 4.5% |

**Decision: PASS_RESEARCH.**
- V2 wins on H1 and Q1, which is 2 of 3 markets.
- The worst Brier regression is +0.0014 (TOTAL), inside the 0.002 tolerance.

## Honest reading
- **The regulation-share fix itself did not help.**
  - Full-game TOTAL got slightly worse.
  - The total bias *grew*, from +0.4 to +1.3 points. Moment-matching to the rating total exposes the fact that the ratings over-predict 2025-26 totals. V1's reg-share deduction was partly offsetting that.
- **The H1 and Q1 gains are most likely from freezing the 2024-25 calibration** (quarter shares, SDs, rho), instead of V1's noisy cold in-season calibration. They are probably not from the reg-share fix.
  - The pre-registered design bundles both changes, so this cannot be attributed from this run.
  - A separate pre-registration would be needed: frozen calibration with V1 scaling.
- **The sim under-produces OT.** It goes to OT 2.2% of the time vs 4.5% actual, because quarter residuals are near-independent (rho 0.03). Neither version fixes this.
- **Gains are small** (about 0.001 Brier), and the baseline is weak. There are no market lines, so the market baseline stays MISSING.
- Research only, with no promotion. rest_adj = 0.
