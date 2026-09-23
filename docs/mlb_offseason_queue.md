# SportsEdge MLB offseason queue — Sept 22, 2026 → Opening Day 2027

## Standing rules
- 2027 priority is limited to **one validated MLB lane** across moneyline, run line, and full-game total.
- Nothing is OFFICIAL unless the governed path actually ran. Otherwise: **NOT Model_P · NOT Truth Gate · NOT OFFICIAL**.
- Never invent data, results, evidence, missing opposite-side prices, or closing prices. Missing = MISSING.
- Do not tune on the replay holdout.
- Historical replay is allowed only after the old DraftKings 2021–2025 dataset, or another source, passes the frozen replay audit for timestamp, same-book two-sided pricing, and true closing price.
- If the historical source fails that audit, 2027 validation is forward-capture only.
- No props or period markets until one of ML, run line, or full-game total passes.
- One bounded step per queue run. Quality over speed.

## Phase 0 — finish 2026 / establish the lane
- DONE — Audited candidate historical DraftKings 2021–2025 source. FAIL for governed replay: per-quote timestamp and true closing-price provenance are not established. 2027 defaults to prospective forward capture unless another historical source passes the frozen audit.
- TODO — Freeze the single 2027 candidate lane and its market definitions across ML, run line, and full-game total.
- TODO — Freeze PIT feature eligibility and leakage rules for the candidate lane.
- TODO — Freeze deterministic simulation/versioned RNG and settlement semantics, including push mass.
- TODO — Freeze same-book opposite-side quote binding; never infer the missing side.

## Phase 1 — data and features
- TODO — Build/verify PIT-safe starter, lineup/order, starter workload, bullpen, park, and weather features for the candidate lane.
- TODO — Build training snapshots with source lineage and as-of timestamps.
- TODO — Add missingness/readiness reporting that fails closed rather than imputing unavailable evidence.

## Phase 2 — model and calibration
- TODO — Fit only on the frozen training partition.
- TODO — Calibrate only on the frozen calibration partition.
- TODO — Produce deterministic ML/RL/full-game-total probabilities from one coherent run distribution.
- TODO — Add push-aware fair price and EV calculations using observed same-book two-sided quotes.

## Phase 3 — validation
- TODO — Run temporal/PIT validation without touching the replay holdout for tuning.
- TODO — If and only if the historical market source passed the replay audit, run the frozen historical replay.
- TODO — Otherwise start forward DraftKings capture and validate prospectively.
- TODO — Compare against true captured closing prices and record calibration, CLV, and after-vig results without promotion claims.

## Phase 4 — promotion decision
- TODO — Evaluate the frozen lane against the predeclared validation criteria.
- TODO — Promote only if the governed path passes; otherwise retain research status and document the blocker/failure.
- BLOCKED — Props and period markets remain blocked until one of ML, run line, or full-game total passes.
