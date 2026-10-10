# CFB spread features — attempt 1 (speed run, 2026-10-10)

**Protocol:** `config/cfb_spread_features_prereg_v1.json` (train 2016–2020, holdout 2021–2025)  
**Feature:** 247 talent composite difference (home − away) / 100  
**Returning production:** not present in the current CFBD issue cache; skipped for this speed run.

## Results (n_train = 3297, n_hold = 3628 FBS games with talent and closing spread)

| Metric | Value |
|--------|-------|
| Train β (intercept, talent_diff) | −0.182, +0.122 |
| Holdout RMSE (closing spread alone) | 15.286 |
| Holdout RMSE (+ talent) | 15.291 |
| RMSE improvement | −0.005 |
| Talent weight | +0.1225 |
| Season-clustered 95% CI | [−0.076, +0.321] |
| CI entirely above 0 | **No** |
| RMSE better than close | **No** |
| **PASS** | **No** |

## Decision
Attempt 1 fails both success criteria. The 8 unsupported spread picks from the morning board stand. Full feature build (QB status, portal, coaching, schedule spot, and returning production once cached) continues as attempts 2+.

No guard changed. No card update. Do not merge.
