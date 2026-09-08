# NFL ATTEMPT_001 residual diagnostic

Status: DIAGNOSTIC ONLY. No model revision, promotion, floor or eligibility change.

Frozen code: `7863d13a9b0353ff95706b1bd0566408b2e7ae62`. All 33 source entries matched the recorded hashes. Reconstructed 1,939 historical rows and 1,447 held-out predictions for 2020–2025. The 2022–2025 calibrated market evaluation remains the original failed attempt.

Residual means below are actual total minus predicted total. Low/middle/high groups use within-fold realized-total thirds, with ties retained together. Counts differ from actionable spread/total counts because these are score predictions before market-price availability and push filtering.

| Season | Games | Mean residual | RMSE | Low / middle / high residual | Outcome-on-prediction slope |
|---|---:|---:|---:|---|---:|
| 2020 | 253 | 3.28 | 14.15 | -10.55 / 3.09 / 18.31 | 0.451 |
| 2021 | 258 | -2.07 | 13.62 | -15.54 / -2.52 / 13.00 | 0.794 |
| 2022 | 179 | -1.86 | 14.35 | -15.94 / -2.08 / 14.58 | 0.578 |
| 2023 | 231 | -2.03 | 13.30 | -14.45 / -2.72 / 13.40 | 1.133 |
| 2024 | 264 | 0.49 | 13.02 | -12.14 / 0.26 / 14.10 | 0.565 |
| 2025 | 262 | 0.14 | 13.71 | -13.72 / -0.37 / 15.73 | 0.647 |

## Interpretation

Low realized totals are overpredicted and high totals underpredicted in every fold. This is not sufficient evidence of harmful shrinkage: conditioning on realized outcomes selects the residual itself. Predicted-total variance is much smaller than outcome variance, but that is expected for conditional-mean forecasts with irreducible scoring noise.

The outcome-on-prediction slopes are below 1 in five of six folds, rather than consistently above 1 as a simple too-compressed-forecast explanation would suggest. They are descriptive, noisy, and not a new fitted production calibrator. The result does not justify globally expanding predictions.

The 2023 totals log-loss failure also coexists with near-extreme calibrated probabilities in the frozen artifact (two observations near 1.0 with one loss), so aggregate mean-bias correction alone does not explain the failed probability evaluation. Attribution to particular features or isotonic tail behavior still requires per-game raw/calibrated probability reconstruction and a separately governed diagnostic. No revised candidate is selected here.

## Preserved limitations

- Original 2022 and 2023 wind exclusions remain attached; this reproduces ATTEMPT_001, not the stricter environment policy in PR #270.
- Original source hashes prove byte identity, not historical availability of each source revision.
- Row-count agreement is checked; per-game probabilities were not retained in the original archive, so exact historical per-game prediction equality cannot be independently compared.
- NFL spread remains 2/4 fold wins and totals 0/4; neither is promoted.
- NFL/CFB prop production wiring and fitted parameter artifacts remain incomplete. MLB/CFB replay and paired-price evidence remain unavailable. Odds quota has not been changed.

## Reproduce

Run `python scripts/diagnose_nfl_frozen_attempt.py --frozen-repo <clean-frozen-checkout> --attempt-bundle <verified-bundle> --output <diagnostic.json>`. The bundle requires the original manifest, validation JSON, preserved schedule and exact recovered source files. The command rejects another code SHA, dirty tracked code, missing files and changed hashes before diagnostic fitting. It never writes a replacement model or promotion registry.
