# MLB delayed-outcome point-in-time baseline research

Research-only. No pricing, odds, capture, activation, or PLAY.

Audit finding: the chronological trailing-rate evaluator in draft PR #2312 advances a player's history after each event-time row without requiring an outcome-observed timestamp. A later pregame forecast can therefore consume an earlier game's outcome that was not yet available at that forecast's cutoff. This is a potential temporal leakage channel even when event timestamps are sorted.

Proposed correction: require forecast_at, event_time, and outcome_observed_at on every row; require forecast_at < event_time <= outcome_observed_at; release outcomes to the subject+market trailing window only when outcome_observed_at <= the next forecast_at; keep equal-time forecast batches isolated; reject duplicate (event_id, subject_id, market); compare fixed league, trailing, and shrunk rates by chronological log loss and Brier on identical rows.

All source claims remain unauthenticated without independent URL/timestamp checks. Market probabilities remain unverified until matched fresh quotes and prospective grading. NFL G2 Attempt 2 NO-GO, G1 exhausted; no holdout use, backfill, archival collectors, capture activation, or threshold changes.
