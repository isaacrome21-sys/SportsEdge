# SportsEdge Bet Ledger V1

## Purpose

Keep research/manual bets permanently separate from reproducible pipeline output while preserving the information needed for later CLV, calibration, and execution analysis.

## Source classes

Every row MUST have `source`.

- `manual_analysis` — selected from human/chat analysis rather than a reproducible SportsEdge pipeline run.
- `pipeline` — emitted by an executable SportsEdge runner with a frozen model/config identity.

Rows MUST NOT be relabeled from `manual_analysis` to `pipeline` after the fact.

## Schema

Required identity/execution fields:

- `bet_id`
- `placed_at_utc`
- `event_id`
- `sport`
- `market`
- `selection`
- `line`
- `american_odds_taken`
- `sportsbook`
- `stake`
- `source`

Optional evidence fields:

- `model_probability`
- `no_vig_market_probability`
- `model_version`
- `model_commit_sha`
- `config_hash`
- `closing_american_odds`
- `closing_line`
- `clv_probability_points`
- `result`
- `profit_loss`
- `settled_at_utc`
- `notes`

## Manual-analysis rule

Historical/manual bets are legitimate research records, but `model_probability`, `model_version`, `model_commit_sha`, and `config_hash` MUST remain null unless they were durably captured at bet time by the pipeline. They are never reconstructed from hindsight.

## Pipeline rule

A `pipeline` row is valid only when the model/config identity and point-in-time model probability were captured before the event. Missing identity means the row is not eligible for pipeline calibration.

## Calibration separation

Manual and pipeline rows MUST be reported separately. Manual-analysis outcomes MUST NOT enter model Brier score, log loss, promotion evidence, or fitted calibration weights.

Parlays/boosts are execution/research records. Core calibration evaluates their underlying independently priced legs; parlay ROI does not become model calibration evidence.

## Evidence floor

Per-market fitting/calibration requires `n >= 300` eligible settled `pipeline` observations. Below that floor, the dashboard state is `INSUFFICIENT_EVIDENCE`; it must not present a fitted/calibrated metric as decision evidence.
