# CFB 2025 holdout lock

Status: candidate lock only. Not a game-model freeze. Not Saturday pricing.

## Decision

Option 2 from the 2026-09-30 restart: freeze the current joint identity, grade 2025 against CFBD last-stored closes, keep the phone card `NO_MODEL`.

`config/cfb_game_model_freeze.json` stays `UNFROZEN`.
PR #1251 stays a fail-closed intake path, not a pricing merge.

## What is locked

- Family: `CFB_JOINT_MODEL_V1` / `cfb_joint_ridge_residual_v1`
- One shared score simulation for moneyline, spread, and total
- Market-blind features only
- Closes: CFBD last-stored lines (`docs/CFB_1070_CLOSE_VS_SNAPSHOT.md`)
- Fit cutoff: seasons through 2024; holdout season 2025

## What is not granted

- Model_P
- Truth Gate
- Official
- Evidence clock
- Week-6 Saturday prices

## Pass rule

Recorded in `config/cfb_2025_holdout_lock_v1.json`:

- at least 200 graded ATS games
- at least 40 high-confidence ATS games (`|p_cover - 0.5| >= 0.08`)
- high-confidence ATS hit rate at least 0.52 versus the last-stored close
- zero market/outside-projection contamination in the score

Overall ATS can be reported. It cannot pass the lock by itself after week 4's 6-3 / top-picks 1-2.

## Saturday

`saturday_card_status()` always returns `NO_MODEL:CFB_2025_HOLDOUT_INCOMPLETE` while the lock is `HOLD_PENDING` or `HOLD_FAIL`.

Even `HOLD_PASS` returns `NO_MODEL:CFB_PROMOTION_NOT_GRANTED` until a later explicit promotion write. That write is out of scope here.
