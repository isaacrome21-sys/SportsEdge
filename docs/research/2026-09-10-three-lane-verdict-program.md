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
