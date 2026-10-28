# PINS — Gap Source Hunt (Oct 27–28, 2026)

All hashes measured locally from the actual downloaded bytes during the hunt.
A pin identifies the exact bytes inspected; it is not a redistribution license.

## Kaggle NBA file — GitHub MIRROR (see HUNT_REPORT §2.2)

| Artifact | Location | Bytes | sha256 |
|---|---|---|---|
| `nba_2008-2026.csv` (mirror) | `andrewgkim-neu/nba-playoff-predictor :: data/kaggle/nba_2008-2026.csv` | 2,493,308 | `729eb2ead85c14affbb81ae9a4c611fee9790b8dd3d1d7824e1ddba14410a8c4` |

Measured: 24,440 rows × 27 cols; dates 2007-10-30 → 2026-06-13.
Kaggle original: `cviaxmiwnptr/nba-betting-data`, file `nba_2008-2026.csv`, stated
2.49 MB, page updated 2026-06-15, license CC0 per in-repo DATASET_REGISTRY.
Identity basis: filename + exact byte size + identical schema + identical coverage.
NOT cryptographic vs the original (Kaggle publishes no hash). Label: MIRROR.

## SmartStake MLB player props — sample partitions pulled (see §3.1)

Dataset: `SmartStake/mlb-player-props` (Hugging Face), CC BY 4.0,
20 parquet partitions, 901,411,520 bytes total (`usedStorage` at pull time).

| Partition | sha256 |
|---|---|
| `mon=2026-03/part-000.parquet` (1,432,405 rows) | `c1058237807fbd39306a3b5091460cf4c02e63948e457e3c0a2a3b1aa4e0fba3` |
| `mon=2026-05/part-002.parquet` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `mon=2026-06/part-000.parquet` (111,148 rows) | `4562a833a70b1c483383b9ddfb0a770b62859d8c3fd571fe19130276f0d682dc` |
| `mon=2026-06/part-003.parquet` | `8ed057db5877a206845f4d3781bda0ade2d0e107c1372d5bfb47203b721d420c` |

## SBR NCAAB seasonal Excel — via Wayback (see §5.1)

Source: `sportsbookreviewsonline.com/scoresoddsarchives/ncaabasketball/ncaa basketball YYYY-YY.xlsx`

| Season | Bytes | sha256 |
|---|---|---|
| 2007-08 | 501,270 | `85cc49aebffa407883e5752fb6803d96d68b15b99fab6e9f7f9bc64435fe3430` |
| 2013-14 | 543,957 | `72bf8c33a3339dfa161acbd24b0dd58d4af27e7511661adffbb0b96effe73ab9` |
| 2018-19 | 669,260 | `7d1ba21b9d65860b87266c61ecbe9fbf59fb79ad022ab673b7def0b732f51703` |
| 2019-20 | 635,890 | `9b82b24bba0b12873e57c7e9ac9215495473e578f83c8357292e282aad549178` |
| 2020-21 | 469,599 | `88a57ee24303d40dc68b43662776b5afcac61e3ad68da4fb8961cfd12ea9ca5d` |
| 2021-22 | 652,845 | `df4d4431580a4e45a8206f2a4c5f82268204329566e19cf06729953af7d17a36` |

Snapshots used: 2007-08 `20151026181233`; 2013-14 `20151026181503`;
2018-19 `20200517022937`; 2019-20 `20221020195709`; 2020-21 `20221020195648`;
2021-22 `20221020195705`. Full archive enumerated 2007-08 → 2021-22 (15 files).

## SBR NBA seasonal Excel — via Wayback (see §5.2)

Source: `sportsbookreviewsonline.com/scoresoddsarchives/nba/nba odds YYYY-YY.xlsx`

| Season | Bytes | sha256 | Note |
|---|---|---|---|
| 2021-22 | 183,871 | `23f287c2723db80ed3978557d37f34f5b7957cf638d709ad2923282aae6d09f4` | snapshot `20230123013503`; 2,646 rows (full season) |
| 2022-23 | 95,253 | `29ee5af73be64b3c4d2a50ae07dd3a1593e6ab90975ab6ed7ce5dbb2c9dbab28` | snapshot `20230123013519`; 1,328 rows (partial, through ~2023-01-22) |

## PropLine sample (REJECTED as data — §3.2)

| Artifact | sha256 |
|---|---|
| `propline/graded-player-props-sample :: nfl_graded_props_14d.csv.gz` | `053f6a5ef9b68ee4eb9f4f9bb71fe6daf9e3759d092c414bd1df28ea0b2a7b5c` |
