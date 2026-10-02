# CFB 2025 one-shot holdout pre-registration

Status at pre-registration: **NOT RUN**. This file and `config/cfb_freeze_v1.json`
must be committed before any 2025 holdout metric is computed.

## Frozen engine

The test uses `cfb_freeze_v1` exactly as committed. No model logic, feature weights,
ridge alpha, simulation count, or seed policy may change after this pre-registration.
Training is restricted to regular-season FBS games from 2015 through 2024. No row
whose `season >= 2025` may enter model fitting.

For every 2025 target game, team form inputs must be strictly prior: week 1 uses the
prior-season fallback; week N>1 uses current-season metrics through week N-1 only.
The historical reconstruction is current-provider-vintage and is not represented as
timestamped PIT evidence. Market lines are evaluation-only and never enter model
fitting or score simulation.

## Holdout population and line contract

Population: completed 2025 regular-season FBS-vs-FBS games present in the frozen
reconstructed feature materialization and CFBD `GET /lines`.

Per #1267, CFBD historical `spread` and `overUnder` fields are treated as the
provider's **last-stored historical lines** (historically described as closing lines),
not as timestamp-certified kickoff snapshots. `spreadOpen`/`overUnderOpen` are not
used.

Exactly one provider is selected without looking at scores or model outputs:
1. among provider names with both stored spread and total, count matched holdout games;
2. choose the provider with the greatest complete-game coverage;
3. break ties by case-insensitive provider name, then exact provider name.
One game contributes at most one evaluation row.

CFBD spread is interpreted as the home-team spread. The market margin forecast is
`-home_spread`; the market total forecast is `overUnder`.

## Metrics fixed before the run

On the complete matched game set:
- **Home-margin RMSE, model:** RMSE of the mean simulated home-minus-away margin versus
  realized home-minus-away margin.
- **Home-margin RMSE, CFBD close:** RMSE of `-home_spread` versus realized margin.
- **Total RMSE, model:** RMSE of the mean simulated total versus realized total.
- **Total RMSE, CFBD close:** RMSE of the stored total versus realized total.

Calibration uses only the applicable half-point closing lines. A line is a half-point
when twice the line is an odd integer (within numerical tolerance).
- **Home cover:** observed = `realized_margin + home_spread > 0`; predicted = fraction
  of simulated paths satisfying the same inequality.
- **Over:** observed = `realized_total > closing_total`; predicted = fraction of
  simulated paths satisfying the same inequality.
- Report predicted event rate, observed event rate, absolute calibration gap, and
  Brier score for home-cover and over subsets.

## Pass rule fixed before the run

**PASS** only if all three conditions hold:
1. model home-margin RMSE <= CFBD closing-line home-margin RMSE + **0.25**;
2. half-point home-cover absolute calibration gap is **< 0.05**;
3. half-point over absolute calibration gap is **< 0.05**.

Otherwise the result is **FAIL**. Total RMSE and both Brier scores are mandatory
reported diagnostics but are not additional gates. If either half-point subset is
empty, the test FAILS rather than relaxing the rule.

## One-shot rule

The runner requires the literal confirmation `RUN_2025_HOLDOUT_ONCE`, refuses
training rows from 2025 or later, and refuses to overwrite an existing result. No
re-run, tuning, alternate provider selection, changed threshold, or post-result model
change is permitted in this PR.

If PASS, the same PR may wire this exact freeze into the CFB phone-card `[CFB LINES]`
path for ML/spread/total pricing. If FAIL, the card remains `NO_MODEL`.
