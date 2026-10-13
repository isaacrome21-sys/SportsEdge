# Review: replay/freshness impact of post-fetch `retrieved_at`

Branch `fix/mlb-receipt-bounds-20261013`. Shared runner paths; needs ChatGPT review.

## Consumers of `GameSnapshot.retrieved_at` (from `fetch_schedule`)
| consumer | check | affected? |
|---|---|---|
| `mlb_postseason_k_outs_forward_shadow.build_prediction` | `retrieved_at > captured_at` → `SCHEDULE_FETCH_AFTER_CAPTURE` | **No.** Its runner builds games with `parse_schedule(..., captured)` directly, not `fetch_schedule`. The check is a correct direction guard. |
| `mlb_pitcher_k_historical_row` | copies `retrieved_at` into the row | Value now equals real receipt time (provenance becomes more accurate); no comparison |
| `mlb_savant_features._checked_snapshot` | TTL vs wall clock | No: `StatcastSnapshot`, not schedule |
| `mlb_statcast_preview_source`, `statcast_daily_source` | copy only | No |

No freshness or staleness check compares a schedule `retrieved_at` against a replay as-of time, so there is nothing to fix there.

## Found and fixed: 8 more callers that would have failed closed
These scripts passed a pre-fetch or historical time as `now=`. Under the new bound they would raise `CALLER_TIME_BEFORE_FETCH_START`. They now pass no `now` (receipt = post-fetch clock). Their own as-of logic is unchanged:
- `archive_mlb_additional_odds.py`
- `capture_mlb_moneyline_model_p.py`
- `capture_mlb_pitcher_k_forward.py` (×2)
- `refresh_mlb_game_context.py`
- `research_mlb_pitcher_prop_promotion.py` (a replay: it previously stamped a historical `observed_at` as the schedule receipt)
- `run_free_mlb_game_markets.py`
- `run_mlb_moneyline_shadow_card.py`

A repo-wide test now fails if any `sportsedge/` or `scripts/` caller passes `now=` to `fetch_schedule`.

## Residual
- In replays, a schedule fetched today carries today's `retrieved_at`. That is the truthful value: a later fetch cannot prove what was visible at the historical as-of time, and no consumer treats it as if it could.
