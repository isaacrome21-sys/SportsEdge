# STATUS NOTE — CFB activation designs pack (added Oct 28, 2026, by Rocky)

This pack was written BEFORE the CFB team-totals design screen ran. Its
team-totals documents present CFB_TEAM_TOTAL_POSSESSION_V1 as DESIGN_ONLY /
screen-not-run. That status is STALE. The governing record is PR #2861
(merged Oct 28, 2026), research/cfb_team_total_screen_20261028/:

- CFB_TEAM_TOTAL_POSSESSION_V1: FAILED_SCREEN — RETIRED. Never tuned, never
  resurrected.
- Pooled 2023-2025, n=3,172 team-games / 1,586 games: residual beta -0.0274
  vs the prereg-required >= +0.10 (negative in all three seasons); MAE 9.453
  vs the market-implied split 8.708 (tolerance +0.5; delta +0.745, game-cluster
  bootstrap 95% CI [+0.608, +0.884]). Legs 1-3 of prereg section 4.3 fail
  outright; leg 5 (80% PI coverage 0.827) holds.
- CFB state after #2861 and the G3 audit (PR #2851): sides/totals permanently
  closed (no viable construction on available inputs); team totals v1 FAILED;
  player props = forward capture accrual only.

Read this pack's team-totals documents as the historical design record only.
