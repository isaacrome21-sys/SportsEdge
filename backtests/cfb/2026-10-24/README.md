# Overnight evaluation: attempt 1, interim

This is item 9 of the Oct 24 owner work list. Deadline: Oct 25, 9 AM America/Chicago. It is not a completed all-model report.

The existing SDV model was fitted with unchanged PRIOR_CURRENT_BLEND, ridge alpha 300 and prior-equivalent-games 4, once per test season using only earlier seasons. The last available season (2025) was held out in this diagnostic. This fixes the future-season training in the old LOSO evaluation without altering production model code. However, these family/hyperparameter choices were already made in previous research; this run is not a newly sealed independent experiment.

Input: data branch `history/cfb/sportsdataverse-selection/training_rows.json`, 6,620 rows, seasons 2016–2025. Retrieve the exact source bytes matching the SHA in the result before reproducing. Run:

```sh
python backtests/cfb/2026-10-24/run_sdv_walk_forward.py --rows /path/to/training_rows.json --output /tmp/sdv_diagnostic.json
```

Current-week feature metadata checks passed. All source rows declare RECONSTRUCTED_HISTORICAL_NOT_PIT, and historical weather availability before kickoff is unproven. Consequently this is only a reconstructed score diagnostic, not a cleared PIT test. Paired historical close/entry prices are absent from this input. All market verdicts remain INSUFFICIENT_DATA; EV/CLV/ROI and probability-comparison fields are null, not zero or a fabricated -110 baseline.

Still required: opponent-adjusted model evaluation; actual historical closing quote joins; chronological source-availability audit; requested per-market metrics and comparison verdicts when admissible. No thresholds, production model math or promotion state changed. Each later attempt must use a new result filename and preserve this attempt.
