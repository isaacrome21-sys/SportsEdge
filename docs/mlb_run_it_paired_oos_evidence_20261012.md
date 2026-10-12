# Production RUN IT historical evaluation bridge — status

The generic backtest harness is already on main via #2044 and the
market-baseline readers via #2058. **This is NOT a new model or a replacement
harness.** It is the stricter evidence gate needed before calling an MLB
RUN IT forecast historically evaluated.

## Why this exists

- Generic harness `runner.run_backtest()` accepts predictions without
  the exact archived feature-availability evidence used at pricing time.
- Its baseline leg has no required quote-capture timestamp at the result
  record level and may have a different denominator when closes are missing.
- `report.evaluate()` compares aggregate Brier/log-loss summaries, not a
  paired series-block confidence interval on identical observations.
- A modern StatsAPI game schedule containing a 'probablePitcher' cannot
  prove that identity was known before first pitch in 2024.
- The SBR-derived MLB close dataset lacks guaranteed historical capture
  timestamps. **Do not backdate or pretend these are verified closes.**

These are gaps in certification, not proof that the model lacks skill.

## Strict input contract

`sportsedge.backtest.strict_paired_oos.evaluate(rows)` requires one
record per verified MLB selection with original pregame feature receipts,
prediction-as-of timestamp, last completed training game timestamp,
one fixed model-source SHA, paired same-book contemporaneous prices
captured within 30 minutes before kickoff, and observed settled outcome.

Rows must contain:
`fixture_id`, `series_id`, `market` (ML, TOTAL or SPREAD),
`selection`, `opposite_selection`, `line` (literal `"ML"` for
moneyline), `kickoff_utc`, `as_of_utc`,
`feature_max_available_at_utc`, `train_last_final_at_utc`,
`model_source_sha`, `market_blind=true`, `candidate_p`,
`existing_p`, `outcome` (0 or 1; pushes require a separate push-aware
test), `market_book`, `opposite_book`, `market_yes_american`,
`market_no_american`, `market_yes_captured_at_utc`, and
`market_no_captured_at_utc`.

All market probabilities are derived *inside the evaluator* from the
actual two-sided American quotes. There is no inference from an
untimestamped odds archive or supplied no-vig probability.

Every row is checked, failed rows are explicitly counted, and any
missingness blocks the verdict rather than selectively omitting poor
coverage. The minimum default sample is **300 unique games and 20
independent series blocks**. Four paired metrics are calculated:
Brier and log-loss differences against the existing model, and Brier
and log-loss differences against the sportsbook no-vig quote at the
same game/line. Deterministic series-block bootstrap CIs must be below
zero for every metric to indicate forecasting improvement.

Even an observed improvement yields only
`FORECAST_IMPROVEMENT_RESEARCH_ONLY`. It does **not** establish positive
real-money EV, prove closing-line value, or grant production promotion.
Betting return must be evaluated separately on genuinely pregame
available prices with market-specific pushes and independent holdouts.

## Run

```bash
python scripts/audit_mlb_paired_oos.py \
    --input /path/to/genuine_pregame_rows.json \
    --output /path/to/paired_readout.json
```

No historical pregame receipts satisfying this contract have yet been
verified in the current repository audit. Until the exact rows are
materialized from immutable snapshots, the correct verdict is
**BLOCKED_EVIDENCE**, not PASS. This script does not query the July–August
2024 untouched bullpen holdout and does not add any new live inputs.
