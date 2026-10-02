# Fresh validation window V1

This contract opens the bookkeeping for a new evidence window. It does not open the window, score it, or promote any market.

The 2025 NFL prop usage V1 one-look is spent. Pull request #1357 records workflow 36976714292 / artifact 11213747098 and the lock change from UNSPENT to SPENT_TECHNICAL_FAILURE. The player-stats source returned HTTP 404 before calibration and Brier scoring, so that run has no statistical PASS or FAIL. The fitted V1 candidate is unchanged. Reuse, retry, and retune on 2025 are forbidden.

## What this window may later contain

- MLB prop markets that are still research/LEAN. Each market needs its own frozen artifact, PIT features, paired quotes, settlement, calibration, and edge floor. Full-game moneyline, run line, and total evidence does not transfer.
- NFL team totals, which remain NO_ENGINE on the production capability surface. A research score-grid price is not a production engine. An observation is admissible only if it is priced from the same frozen game path as the game total and home team total + away team total equals the game total.
- NFL player props, which remain NO_ENGINE in `config/football_prop_engine_surface.json`. Unified research prices for QB/RB/WR markets do not create Model_P. Anytime TD stays NO_MODEL until a scoring-composition prior is wired and independently validated.

## Admission rules

A record is rejected when any of the following is true:

- `window_id` is `NFL_PROP_USAGE_V1_2025` or `season` is 2025 for this prop candidate.
- A research, LEAN, NO_ENGINE, or NO_MODEL price is labeled Model_P, OFFICIAL, Truth Gate, or DEPLOYED.
- The feature snapshot is missing or was taken after the quote.
- A two-sided market lacks the opposite price.
- The close is not the same book, or `decision_ts < close_ts < game_start_ts` fails.
- Team totals do not reconcile to the parent game total on the same path.

`config/fresh_validation_window_v1.json` is the machine-readable form of these rules. `sportsedge.research_surface_guard` enforces them. Production `engine_state` is unchanged.
