# M22 single-inning count joint: one-shot research screening protocol (DRAFT)

**UNFROZEN / UNRUN / NO PROMOTION**. This screen is specified before any historical score or result inspection.

## Construction v1

For each inning N in {2,...,8}, select **completed, observed strictly before the target first pitch** MLB regular-season games with a full top and bottom of N (both halves played). For the target away club and home club, compute actual runs scored and conceded in inning N over prior games; a minimum of 10 completed prior games per club is mandatory. Each team-run marginal is the equal-weight blend of the club's for-runs empirical PMF and the opposing club's allowed-runs PMF. Joint (away_N, home_N) is the Cartesian product of marginals: a **conditional independence research approximation**, not proof of within-inning score independence. Optional fixed m30 league smoothing requires >=200 observed team-inning halves in the strictly-prior pool. There is one versioned joint per N reused for (a) inning runs O/U 0.5/1.5, (b) run line and (c) three-way inning winner. Jeffreys 0.5/cell posterior for settlement readouts. No odds or market prices enter features.

`INNING_9_*` remains named refusal, not implicitly modeled: bottom ninth can go unplayed (home ahead) or terminate during a walkoff, and even a complete-game ninth marginal is selected on score state. Completing it requires a preregistered path/state and missing-half settlement contract; no n=9 projections from n=8 or full-game scale.

`RESULT_AFTER_INNING_*` is a separate *cumulative* three-way market owned by PR #2433 for N={3,5,7}, and is not priced by this proposal. Existing canonical M22 blockers stay byte-identical. No runner or quote binding is proposed.

## Evidence admission

Historical rows are exact MLB gamePk and real team ID bound, event start/completed/observed ISO UTC and `official_innings>=9`, `played_halves=BOTH`, source record SHA-256 and same-inning count fields. A fixed as-of instant must be strictly before target first pitch. Refuse duplicate gamePk, any observation at/after the as-of instant, future evidence, incomplete rows, missing/non-finite/negative integer runs, mismatched innings, and histories with insufficient eligible team samples. The source manifest, event-specific replay hashes and completeness/schedule attestations must be independently verified; operator-supplied hashes do **not** constitute authenticated independent evidence.

## Chronological 2025 regular-season screen (requires owner data pin)

Walk forward through every certified 2025 regular-season fixture, scoring each n=2..8 where at least 10 truly prior observations exist. Refit only on data observed before that fixture at the preregistered clock; no same-day future results, no backfill of missing timestamps. Compare against a no-tuning strictly-prior **league-by-inning** empirical count PMF baseline smoothed with Jeffreys half-cell, using the **same eligible fixtures**. Predeclare binary Brier/log loss for inning 0.5/1.5 runs and multiclass Brier/log loss for inning 3-way; report source-availability attrition, exact test size, fixture dates, CI by date-block bootstrap, and every N as separate family. Run lines require a frozen real quote identity/settlement path and remain `NO_MARKET_TEST` without it.

A readout **BEATS_BASELINE** for a metric only if both Brier and log loss improve with 95% date-block-bootstrap CI upper bounds for candidate-minus-baseline below zero, else `DOES_NOT_BEAT_BASELINE`; insufficient source coverage is `INSUFFICIENT_DATA`. Any posterior tuning/new feature after inspecting outcomes is a new challenger with a new version and a new clock, never a retroactive repair. This is not a market test; even a calibration win cannot lift an eligibility or PLAY hold.

**Actual execution:** NOT RUN. No independently pinned PIT 2025 source archive/manifest provided in this build. Never claim numeric backtest results or validation without that source.
