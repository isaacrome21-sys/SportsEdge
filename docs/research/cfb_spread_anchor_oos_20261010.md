# CFB spread anchor — strictly chronological out-of-sample research (2026-10-10)

**Decision: NO_PROVEN_SPREAD_EDGE_LANE_OFF.** Research only; do not enable spread model bets. The 95% season-clustered interval for the incremental raw-margin slope covers zero. The walk-forward market-anchor forecast has *worse* pooled held-out RMSE than the historical closing-spread proxy.

## Provenance and no-lookahead

- Research workflow: [run 38055524053](https://github.com/isaacrome21-sys/SportsEdge/actions/runs/38055524053), **success** (chronology tests and 2021–2025 fit).
- Uploaded artifact: `cfb-spread-anchor-oos-research`, artifact ID `11671665491`, containing `spread_anchor_oos_research_20261010.json`.
- Source SDV training rows: pinned `data` commit `3958d218b1d838136461474dbeb2eba99bb59bb3`; SHA-256 `32f520c693ad7567667d3dc6a8c281f8a61ae410f1bdf6c9c35d5e07fd18a579`. 6,620 source rows; 5,942 strictly prior-season predictions; 5,852 joined with historical line reference.
- Market reference: issue #1475 season-by-season cached CFBD lines, **reconstructed close proxy** (NOT independently timestamp-verified actual executable DK close; NOT PIT-certified).
- For test season S, raw SDV model is trained only on seasons < S. Anchor slope/intercept are fitted only on earlier seasons' past-only forecasts and outcomes, not season S. Each test year is unseen at fit time.
- Compare `market + intercept + weight * (raw model home margin - market home margin)` with market-alone and intercept-only baselines. Inputs are game-score model forecasts and retrospective market line references used for *research*, **never features for production Model_P**.
- The reported held-out pooled slope diagnostic uses test-year results only to quantify incremental signal; it is not itself a deployable coefficient. CR1 standard error clustered by held-out season; five clusters, cautious inference.

## Year-by-year, genuinely held-out

| Test season | Previous training seasons end | n | anchor weight fitted on earlier seasons | Market RMSE | Anchor RMSE |
|---|---:|---:|---:|---:|---:|
| 2021 | 2020 | 661 | −0.072344 | 15.7975 | 15.7909 |
| 2022 | 2021 | 691 | −0.067688 | 15.1880 | 15.1923 |
| 2023 | 2022 | 698 | −0.053315 | 15.2067 | 15.2063 |
| 2024 | 2023 | 697 | −0.052043 | 15.3655 | 15.3807 |
| 2025 | 2024 | 706 | −0.045794 | 15.0574 | 15.0653 |

## Pooled held-out performance, n=3,453

| Method | RMSE (points) | MAE (points) |
|---|---:|---:|
| Historical reconstructed close alone | **15.319654** | 12.129959 |
| Close + trained historical intercept only | 15.321467 | 12.134260 |
| Close + walk-forward anchor intercept and slope | 15.323820 | **12.129765** |

The anchor worsens RMSE by **0.004166 points** relative to the market alone (and 0.002353 versus intercept-only), although MAE is fractionally lower by 0.000194. Neither tiny numerical difference is grounds for deployment.

**Incremental held-out slope diagnostic:** −0.017848; 95% season-clustered t interval **[−0.051212, +0.015516]**, standard error 0.012017, 5 independent season clusters. **Includes zero.** Predicted raw score margin does not show a statistically resolved *positive* contribution beyond the historical closing spread.

## Decision / limits

- Under the user's rule, no validated spread signal; **spread model lane stays OFF**. Do not lower edge/ROI gates, amplify anchor coefficients, label as OFFICIAL, or promote small-stake probation to standard bets.
- Prior frozen development anchor in production is ~−0.033174 (6,498 development rows), but it **does not override** the sequentially held-out result. No change to frozen weight.
- Retrospective cached line references can be biased by timestamp uncertainty and are not execution-validating prices; five-season-cluster inference is limited. Research cannot claim confirmed betting EV or prospective profits.
- This PR only adds research script, tests, workflow, and this report. **No runtime changes. Do not merge pending review.**
