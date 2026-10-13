# Research-only CFB spread-anchor walk-forward: 2026-10-10

**Decision: NO PROVEN INCREMENTAL SPREAD SIGNAL. Keep spread model betting-authority lane OFF.**

This is retrospective research, not approved Model_P, betting EV, CLV, or forward validation. It neither touches production runtime nor changes the frozen spread anchor in main. Companion runtime/diagnostic change is PR #1953 and is explicitly unmerged.

## Primary result

On **3,453** held-out historical games across **2021–2025**, the diagnostic regression of actual-minus-historical-close-proxy margin on past-only SDV raw-model-minus-close-proxy margin produced:

- **Pooled held-out diagnostic weight = −0.017848**
- **95% CI = [−0.051212, +0.015516]** (CR1 season-clustered standard error 0.012017; Student t with 4 d.f.; **5** annual clusters)
- **CI covers 0. The raw SDV margin adds no statistically demonstrated predictive signal beyond the market reference.**
- Caveat: the pooled slope is *diagnostic*, computed from heldout outcomes; it is **not** an independently deployable anchor. Five clusters provide limited inferential precision.

Walk-forward margins compared on identical held-out games:

| Predictor | Pooled RMSE (points) | Pooled MAE (points) |
|---|---:|---:|
| Historical close-spread proxy | **15.319654** | 12.129959 |
| Prior-fit intercept-only adjustment to market | 15.321467 | 12.134260 |
| Prior-fit intercept **and** raw-model-gap weight | 15.323820 | 12.129765 |

Walk-forward anchor RMSE changes: **−0.004166 points improvement vs market** (worse), **−0.002353 vs intercept only** (worse).

## Seasonal fits and truly future-season evaluation

The *SDV score* model for each historical game is trained solely on seasons strictly earlier than that game's season. The *anchor* for each held-out season is separately fit only on earlier seasons' already past-only model forecasts and historical outcomes. Neither held-out season outcomes nor future seasons enter either fit.

| Test year | Last train year | Historical rows fitted | Test games | Earlier-only anchor intercept | Earlier-only anchor weight | Market RMSE | Anchor RMSE |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2021 | 2020 | 2,399 | 661 | −0.091342 | −0.072344 | 15.7975 | 15.7909 |
| 2022 | 2021 | 3,060 | 691 | −0.175836 | −0.067688 | 15.1880 | 15.1923 |
| 2023 | 2022 | 3,751 | 698 | −0.267261 | −0.053315 | 15.2067 | 15.2063 |
| 2024 | 2023 | 4,449 | 697 | −0.220870 | −0.052043 | 15.3655 | 15.3807 |
| 2025 | 2024 | 5,146 | 706 | −0.099776 | −0.045794 | 15.0574 | 15.0653 |

Out-of-sample raw model forecasts were made for **5,942** games; **5,852** exact-ID joins to historical market records; total training rows **6,620**.

## Provenance, restrictions and reproducibility

- Historic SDV selection training rows: immutable `data` commit `3958d218b1d838136461474dbeb2eba99bb59bb3`, `history/cfb/sportsdataverse-selection/training_rows.json`.
- Training rows SHA256: `32f520c693ad7567667d3dc6a8c281f8a61ae410f1bdf6c9c35d5e07fd18a579`.
- Historical spreads: already cached GitHub issue #1475, seasons 2016–2025. **These are reconstructed historical close references**, not proven time-stamped/executable DraftKings closing offers; market outcome bias could remain. This is *not* a backfilled forward test.
- Repro script: `scripts/research_cfb_spread_anchor_oos.py` and chronology/CI tests: `tests/test_cfb_spread_anchor_oos.py`.
- Exact successful workflow: [run 38055524053](https://github.com/isaacrome21-sys/SportsEdge/actions/runs/38055524053), artifact [cfb-spread-anchor-oos-research](https://github.com/isaacrome21-sys/SportsEdge/actions/runs/38055524053#artifacts), artifact ID `11671665491`.
- No gameplay odds ingestion or API call is part of this model study. No stake, OFFICIAL designation, validation promotion, or live policy authority. Frozen 2016–2025 anchor remains untouched.

**Conclusion: CI includes zero and anchor RMSE does not outperform the historical market reference. Keep the spread model's bet/official lane OFF pending genuinely new prospective evidence.** A historical five-season small-cluster CI and reconstructed historical reference cannot justify staking.
