# Three-lane definitive verdict program — 2026-09-10

Status: Phase A recorded. No production model, Model_P artifact, Truth Gate pass, or OFFICIAL eligibility is created by this record.

## Shared measuring stick

All three policies now reserve the same chronological shape:

- Training: 2010-2016
- Validation: 2017-2019
- Future forward holdout: 2026, evaluated only once after feature freeze
- Feature-attempt budget: 10 per sport
- Placebo: 200 deterministic training/CV shuffles before feature evaluation
- Market metric: paired model-minus-closing-line RMSE bootstrap with 2,000 replicates and the 2.5th/97.5th percentile 95% interval
- Control: matched baseline is budget-neutral only as a denominator
- Any candidate selection, tuning, or post-result revision consumes an attempt

## Phase A status

### NFL — PARTIAL

NFL has a historical closing benchmark in nflverse and an active widened policy. Attempt 1 (opponent-strength) was run under an earlier 2019-only design and remains historical evidence. Attempt 2 (quarterback) is implemented as a dispatch-only workflow but has not produced a widened-window result. Final verdict: BLOCKED pending the matched 2017-2019 control/candidate run.

### CFB — BLOCKED

The result feed is available through the existing ESPN path. A historical closing-price benchmark was not established from free sources: the existing CFBD path requires configured credentials, and ESPN is being used for results, not historical closing prices. Verdict: BLOCKED_NO_CLOSING_BENCHMARK. No feature attempts are allowed.

### MLB — BLOCKED

MLB StatsAPI and Retrosheet provide game/result data, but no verified free historical closing-price archive is present in the repository or current acquisition path. The existing historical odds path is paid Odds API evidence and the quota is unreconciled. Verdict: BLOCKED_NO_CLOSING_BENCHMARK. No feature attempts are allowed.

## Decision

Do not fabricate CFB or MLB closing lines, and do not spend feature attempts without a benchmark. Run NFL Attempt 2 only after the widened control/candidate workflow is manually dispatched. A definitive NFL verdict requires its resulting interval, close-game split, placebo status, and future-holdout/calibration gates.

## NFL Attempt 2 readout

Attempt 2 used pregame nflverse quarterback identity and prior-quarterback history on the frozen 2017-2019 validation window. It completed successfully under commit b9c3b09.

- NFL margin: candidate RMSE 13.6314; closing spread RMSE 13.1949; model-minus-close +0.4365; paired-bootstrap 95% CI [+0.1989, +0.6687].
- NFL total: candidate RMSE 14.0439; closing total RMSE 13.6406; model-minus-close +0.4033; paired-bootstrap 95% CI [+0.1814, +0.6164].
- Matched control: margin RMSE 13.8462; total RMSE 14.0601. The candidate improved margin versus control by 0.2148 RMSE and total by 0.0163 RMSE, but neither beat the closing market.
- Training-only placebo null used 200 shuffles. NFL margin holdout placebo R2 +0.0295 was at the null 95th percentile +0.0295; NFL total holdout placebo R2 -0.0139 was inside its null p95 +0.0162.

Attempt 2 result: FAILS_BAR. Eight NFL feature attempts remain. No certification or eligibility change is permitted.

## Close-game diagnostic readout

The widened-window rerun completed under commit 1835c63. The close-game diagnostic is now present for candidate and matched control.

- NFL QB margin, absolute actual margin <=7: n=362, candidate RMSE 6.6080 versus mean-baseline RMSE 5.1090, R2 -0.6729. Matched control RMSE 6.7686, R2 -0.7552. The candidate improves over control but remains worse than the mean in close games.
- CFB baseline margin, absolute actual margin <=14: n=1,367, model RMSE 12.1302 versus mean-baseline RMSE 9.3337, R2 -0.6890. This reinforces the prior close-game failure; CFB still has no closing-price benchmark and no feature attempts are allowed.

The NFL QB candidate therefore remains FAILS_BAR. The NFL next candidate is EPA-based efficiency (Attempt 3), subject to the same frozen window and benchmark criterion.


## NFL Attempt 3 implementation (2026-09-10)

Attempt 3 is registered as a deliberate, dispatch-only research run:
- Feature family: EPA-based offensive/defensive efficiency, split pass/rush.
- Source: nflverse play-by-play parquet, fetched on the runner; no odds fields are used as features.
- Point-in-time rule: each game's EPA is appended to team history only after all games on that date emit features. Defensive EPA is the opponent's offensive EPA for that prior game.
- Window: training 2010-2016; immediate validation 2017-2019 from the frozen NFL policy.
- Control: matched raw-points baseline on the same window; budget-neutral.
- Benchmark: raw nflverse `spread_line` and `total_line`, with the required paired-bootstrap 95% CI of model-minus-close RMSE.
- Workflow: `.github/workflows/nfl-epa-attempt3.yml`; report: `artifacts/football_baselines_attempt3.json`.
- Status before execution: implementation complete; no attempt is counted and no result is claimed until the workflow produces a report.


## NFL Attempt 3 result (run 34486772747)

Status: DONE for the attempt; FAILS_BAR for both NFL targets.

- Source coverage: 2,210 EPA-enriched games; 2,157 usable point-in-time rows.
- Window: train 2010-2016; validate 2017-2019; 731 games with closing lines.
- Margin: model RMSE 13.9436 versus closing spread RMSE 13.2077; delta +0.7359; paired-bootstrap 95% CI [+0.4225, +1.0522]. Close-game (absolute margin <=7) R² was -0.6489 versus the mean.
- Total: model RMSE 14.1336 versus closing total RMSE 13.6565; delta +0.4771; paired-bootstrap 95% CI [+0.2419, +0.6983].
- CV alphas: margin 10.0; total 300.0.
- Placebo status: training-only placebo R² was negative for both targets (margin -0.0604; total -0.0031), with no placebo-based leakage indication.
- Decision: EPA efficiency did not clear the frozen criterion. Do not freeze an artifact, change eligibility, or promote Model_P. Attempt 3 is consumed; next registered NFL family is situational features.
- Evidence: report artifact digest `sha256:196513ef937aefd20225664ece27f930e608618e85a31334d9f9d02601f95534`.
