## Promotion gate (unchanged)

On **2026-08-01 → 2026-08-31** only:

1. Mean absolute calibration gap on game totals 6.5 / 7.5 / 8.5 / 9.5 improves
   vs defense blend, and
2. Mean Brier on those four lines improves vs defense blend,

under the shipped Stage-1 dispersion. Both required. Secondary metrics (MAE,
mean error) are descriptive.

If either gate fails, production stays on defense blend.

### One-shot rule

**August is scored once.** Publish the v2 numbers; if the gate fails, v2 is
dead. A tweaked v3 does **not** get a second look at August — it needs a new,
unused pre-registered window. Re-running August after changing constants is
tuning on the test set.