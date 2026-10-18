# Result: NBA game-market walk-forward on 2025-26 (fresh season) — PASS_RESEARCH

- **Pre-registration:** `NBA_QUARTER_SIM_2025_26_OOS_PREREG_20261013.md`, committed in 6a2ef2c before any 2025-26 data was fetched.
- **Code:** frozen. Branch code was unchanged since 6843c23; the prereg commit only added the doc.
- **Data:** free ESPN, 1,235 completed regular-season games from 2025-10-21 to 2026-04-12. 1,231 loaded, 4 skipped as invalid. Cache is outside the repo.
- **Lines:** naive stand-ins. Market baseline MISSING.

| market | n | model Brier | naive Brier | model log-loss | naive log-loss |
|---|---|---|---|---|---|
| MONEYLINE | 1076 | **0.2054** | 0.2482 | **0.5990** | 0.6896 |
| SPREAD (naive proxy line) | 1076 | **0.2080** | 0.2498 | **0.6048** | 0.6928 |
| TOTAL (naive proxy line) | 1076 | **0.2316** | 0.2485 | **0.6557** | 0.6901 |
| H1 total (stand-in, not gating) | 1076 | 0.2405 | 0.2496 | 0.6740 | 0.6924 |
| Q1 total (stand-in, not gating) | 1076 | 0.2458 | 0.2499 | 0.6848 | 0.6930 |

ML vs margin path inconsistency is 0.0.

**Decision: PASS_RESEARCH.** All three gating markets beat naive on both Brier and log-loss.

## Reading
- **Consistent with 2024-25.** The results are close to the 2024-25 numbers (ML Brier 0.211, spread 0.213, total 0.227). There is no sign of overfitting to the development season.
- **Weak baseline.** "Naive" is a train-mean proxy. Beating it shows the ratings carry signal; it is **not** evidence of an edge against DK prices, and real paired timestamped closing lines are still required.
- **Retrospective data.** Data was fetched after the season. Point-in-time correctness rests on start-time filtering, not on independently timestamped receipts.
- **No authority.** No promotion, eligibility or stakes.
