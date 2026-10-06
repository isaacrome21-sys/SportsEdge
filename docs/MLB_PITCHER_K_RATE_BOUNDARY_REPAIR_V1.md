# MLB pitcher-K empirical rate boundary repair

Status: technical pre-evaluation repair. No candidate metrics were produced by the failed Attempt 1 materialization, so this is not post-readout tuning.

## Verified contract

Frozen preregistration `MLB_PITCHER_K_PROBABILITY_PREREG_V1` lists `recent_mean_k_per_batter_faced`, `whiff_rate`, and `chase_rate` as features of `BINOMIAL_LOGIT_K_RATE` with `standardization: TRAINING_ONLY_MEAN_AND_SCALE`. The logit is the rate-model link for the realized K/BF target, not a feature transform.

Skill binding already accepts an empirical rate of exactly 1.0 when the raw counts match (`whiffs == swings` or `chases == out_of_zone_pitches`) and rejects counts above the denominator. A reported failing row is pitcher `689225`, game `746754`, date `2024-08-25`, `chase_rate=1.0` from 1 chase on 1 out-of-zone pitch.

`feature_vector()` previously rejected those rates with `>= 1`. That check was tighter than the frozen feature semantics and blocked candidate scoring before any readout. Branch `research/mlb-pitcher-k-attempt1-rate-boundary-repair` (`bfacd4f`) locked the rejection; it is not the repair.

## Correction

Accept empirical rates in `(0,1]`. Continue to reject zero, negatives, values above 1, non-finite values, and incomplete sources. Do not clip or coerce invalid rates.

This change does not alter the ridge grid, season split, holdout, incumbent, or promotion authority.
