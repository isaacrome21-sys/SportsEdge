# NFL environment source measurement — 2026-09-08

Source: https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv

SHA256: f04cfa47d207607afbd883147abc495eab39e8f29fb42ab57027fa2f8f5bf355

Regular-season rows, 2016–2025. This measures the acquired schedule, not paired market evidence. No promotion or floors are authorized.

| Season | Rows | Missing home rest | Missing away rest | Missing wind | Missing wind_mph | Missing roof |
|---|---:|---:|---:|---:|---:|---:|
| 2016 | 256 | 0 (0.0%) | 0 (0.0%) | 64 (25.0%) | 256 (100.0%) | 0 (0.0%) |
| 2017 | 256 | 0 (0.0%) | 0 (0.0%) | 64 (25.0%) | 256 (100.0%) | 0 (0.0%) |
| 2018 | 256 | 0 (0.0%) | 0 (0.0%) | 65 (25.4%) | 256 (100.0%) | 0 (0.0%) |
| 2019 | 256 | 0 (0.0%) | 0 (0.0%) | 66 (25.8%) | 256 (100.0%) | 0 (0.0%) |
| 2020 | 256 | 0 (0.0%) | 0 (0.0%) | 91 (35.5%) | 256 (100.0%) | 0 (0.0%) |
| 2021 | 272 | 0 (0.0%) | 0 (0.0%) | 90 (33.1%) | 272 (100.0%) | 0 (0.0%) |
| 2022 | 271 | 0 (0.0%) | 0 (0.0%) | 175 (64.6%) | 271 (100.0%) | 0 (0.0%) |
| 2023 | 272 | 0 (0.0%) | 0 (0.0%) | 122 (44.9%) | 272 (100.0%) | 0 (0.0%) |
| 2024 | 272 | 0 (0.0%) | 0 (0.0%) | 99 (36.4%) | 272 (100.0%) | 0 (0.0%) |
| 2025 | 272 | 0 (0.0%) | 0 (0.0%) | 95 (34.9%) | 272 (100.0%) | 0 (0.0%) |

Policy: exclude invalid environment rows from evaluation, retain observed PBP for prior state, count exclusions per season with composite reasons (one count per row). Never impute closed-roof wind. The optional wind_mph alias falls back to wind only when absent; malformed supplied aliases are excluded.

No season is wholly absent on wind alone, but combined QB, venue, prior-season and other requirements may reduce usable folds further. This measurement cannot establish minimum actionable sample sizes.

The production validation command writes nfl_environment_coverage.json before loading PBP/participation/depth, so a later source failure cannot hide the schedule preflight. Old artifacts are not reused by this change. A new replay and exact-head hosted verification remain required.
