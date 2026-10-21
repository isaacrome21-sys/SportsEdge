# M50 terminal-score research screen — DRAFT, NOT FROZEN OR RUN

**Construction version:** `mlb_m50_terminal_score_readout_v1_jeffreys`  
**Source model:** existing, unchanged `sportsedge.game_total_distribution.GameTotalDistribution`.  
**Target:** 2025 MLB regular season. **Train/history:** only fully completed games observed strictly before each test fixture start, with the source model's existing minimum-history and optional m30 pool rules unchanged. No later score is available to the candidate. Identical eligibility set for all comparators.

**Prerequisite evidence**: independently pinned, deduplicated gamePk, UTC scheduled first pitch, source observed-at timestamp, completed inning/final score, away/home team identity and score-revision audit from the already sanctioned StatsAPI source. Reject any game with mismatched team identity, duplicate gamePk, observed-at after test start, missing as-of pin, negative final runs, or historical game with unverified completion time. A source hash and feature SHA per game are required before evaluation. No backfill of refused evidence.

## One-shot scoring, set before inspecting results
Four independent family readouts share one fixed full-game joint. No per-family hyperparameter tuning or retraining.

* **BTTS**: YES/NO each of catalog rungs 1+ through 9+. Settle `away_final >= N and home_final >= N`. Compare pregame binary Brier and log loss per rung against a strictly-prior pooled frequency (Jeffreys 0.5/0.5).
* **Team parity**: HOME/AWAY final runs, ODD/EVEN. Compare binary Brier/log loss against each team's strictly-prior empirical parity rate shrunk to the strictly-prior league parity pool by the same fixed m30.
* **Correct score**: frozen seven-way partition `AWAY_0_HOME_0`, `AWAY_1_HOME_0`, `AWAY_0_HOME_1`, `AWAY_1_HOME_1`, `AWAY_1_HOME_2`, `AWAY_2_HOME_1`, `ANY_OTHER`. Score multiclass Brier/log loss against strictly-prior pooled exact-cell climatology, with Jeffreys half-cell smoothing. A complete partition is mandatory; no partial quoted market is inferred from it.
* **Winning margin**: frozen eleven-way partition `AWAY_BY_5_PLUS`, `AWAY_BY_4`, `AWAY_BY_3`, `AWAY_BY_2`, `AWAY_BY_1`, `TIE`, `HOME_BY_1`, `HOME_BY_2`, `HOME_BY_3`, `HOME_BY_4`, `HOME_BY_5_PLUS`. Score multiclass Brier/log loss against strictly-prior pooled signed-margin climatology, with Jeffreys half-cell smoothing.

Aggregate per-family and per-rung, report test count, source hashes, exact version, abstentions, point differences (candidate minus baseline), and chronological block-bootstrap 95% confidence intervals grouped by game date. **BEATS_BASELINE** only when both Brier and log loss improve and both CI upper bounds for candidate-minus-baseline are below zero. Otherwise verdict is `DOES_NOT_BEAT_BASELINE` or `INSUFFICIENT_DATA` with named evidence. Under no result does this permit PLAY: there is **NO paired historical market leg**, hence `NO_MARKET_TEST` and `NOT_VALIDATED`.

**Prohibited reuse**: do not use historical screen results to alter this construction/version or screening thresholds. Any improvement after reading results is a separately labeled challenger with a new SHA and new clock; never re-report this first screen. No runner/binder/gate changes from this draft.

**Deliberate NO_ENGINE/NO_DATA**: EXTRA_INNINGS requires the ninth-inning tie state; RACE_TO_RUNS and first/last-run require ordered inning paths; GRAND_SLAM requires bases and play attribution. Final score does not determine these events. Never impute outcomes from final scores.

**Execution state:** UNRUN. No pinned source manifest for the 2025 test fixture set was supplied to this build, so no historical results, confidence intervals, or verdicts are asserted.
