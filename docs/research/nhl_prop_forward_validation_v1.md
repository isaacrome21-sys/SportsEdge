# NHL player-shots + goalie-saves forward validation v1

**Declared before the 2026–27 regular-season window begins.** Research only. No card promotion is granted by this document or evaluator.

## Frozen window

- Start: **2026-10-08**
- End: **2026-11-30**
- No prediction created after puck drop is admissible.
- No historical reconstruction may replace a missed prospective prediction receipt.

This uses the same opening live window already reserved for the NHL rate owner, but prop evidence is evaluated independently from ML/puck-line/totals.

## Markets and fixed evaluation grids

| Market | Half-point lines | Primary minimum |
|---|---|---:|
| Player shots | 1.5, 2.5, 3.5, 4.5 | 200 CONFIRMED rows |
| Goalie saves | 21.5, 23.5, 25.5, 27.5, 29.5 | 80 CONFIRMED rows |

The grid is frozen before the window. It is evaluation-only and does not come from sportsbook prices.

## Prediction receipt

Each prospective row must carry:

- market, game id, subject id and one frozen half-point line;
- candidate probability and a paired market-blind baseline probability;
- `captured_at` and official scheduled `start_time_utc`, with capture strictly before start;
- role/starter state (`CONFIRMED` or `PROJECTED`);
- versioned model identity;
- a lowercase SHA-256 identifying the source/input receipt.

Duplicate `(market, game_id, subject_id, line)` rows fail closed. Missing receipts stay missing.

## Settlement

Settlement is a separate postgame row with actual count and `final_at`. `final_at` must be after game start. Half-point lines have no push, so outcome is `actual_count > line`.

## Primary population

Only rows whose pregame role/starter status was **CONFIRMED** count toward the promotion gate. `PROJECTED` rows are reported separately and cannot help a market pass.

## Frozen gates, per market

All must pass on the same confirmed rows:

1. required minimum sample size;
2. candidate Brier score no worse than the paired market-blind baseline Brier score;
3. 10-bin expected calibration error <= **0.05**;
4. absolute mean predicted-vs-observed calibration gap <= **0.04**.

A passing evaluator result is labeled `PASS_ELIGIBLE_FOR_SEPARATE_PROMOTION_REVIEW`. It does **not** change the phone card, Model_P authority, Truth Gate, staking, Score, or OFFICIAL status. Promotion requires a later, separate review/PR.

## Why prospective

The player-shot, goalie-save and peripheral engine plumbing existed before this charter, but no clean unused performance holdout for these exact operational surfaces was frozen. Re-scoring old seasons after seeing implementation choices would be development evidence, not prospective confirmation. This charter therefore starts with the 2026–27 season and prohibits backfill.
