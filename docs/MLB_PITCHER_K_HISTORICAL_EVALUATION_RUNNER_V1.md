# MLB pitcher-K historical evaluation runner v1

Status: **research only; zero betting authority**.

This runner is the execution bridge for the already-frozen pitcher-K probability candidate. It does not alter production pricing. It materializes a deterministic historical development/test sample, evaluates the candidate once on the candidate-specific 2025 test split, and emits an auditable report.

## Frozen sample

The exact sampling contract is `config/research/mlb_pitcher_k_historical_eval_plan_v1.json`.

For each of 2023, 2024, and 2025, the runner uses regular-season games on June, July, August, and September dates 1, 6, 11, 16, 21, and 26. Every completed game on those dates is eligible; both actual starting pitchers are attempted. Dates are fixed before any row is materialized and no early stopping is allowed.

A row is retained only when all preregistered candidate inputs are available:

- 5–10 strictly-prior starts;
- the validated opponent-K component;
- the validated lineup-K component when the actual starting order can be reconstructed, otherwise the existing opponent-K-only fallback;
- a target-date-exclusive 30-day Baseball Savant/Statcast pitcher snapshot with whiff rate, chase rate, and throwing hand;
- realized strikeouts and batters faced for the target start.

Missing inputs drop the row and are counted. They are never imputed from future data.

## Point-in-time and backfill semantics

This is historical reconstruction for the candidate-specific 2023/2024/2025 development protocol. Statcast queries end at the official target date and therefore exclude the target game and all later games. StatsAPI histories are filtered strictly before the target date by the existing feature sources.

Historical source bytes may be cached for transport efficiency. The cache does not grant forward-evidence status. Every emitted row is explicitly marked as historical/backfill and not forward-evidence eligible.

## One-look rule

The candidate evaluator uses:

- 2023: training;
- 2024: hyperparameter selection;
- 2023+2024: refit;
- 2025: candidate-specific test, once.

The 2025 readout is not broader pitcher-prop promotion evidence and cannot directly create Model_P, ACTIONABLE status, staking authority, or OFFICIAL authority. A development pass only permits a separate release/forward-evidence protocol.

## Trigger

After this runner is merged, open an issue titled:

`[MLB RESEARCH] pitcher-K historical evaluation v1`

with the exact fenced directive:

```text
RUN_PITCHER_K_HISTORICAL_EVAL_V1
```

The workflow posts the deterministic report back to that issue and uploads the row materialization and evaluation artifacts.
