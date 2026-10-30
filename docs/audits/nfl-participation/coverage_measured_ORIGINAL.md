# NFL Participation Foundation — MEASURED Coverage

Generated: 2026-10-12T22:46:05Z · Method: measured from nflverse source files; see coverage.py docstring

Denominator for every percentage below is the season's eligible regular-season team-games from the schedule (games × 2), not downloaded record counts. Availability classes follow the owner's four-way scheme. Timing for S3/S4/S5/S6 is CADENCE-INFERRED (final-report rule / prior-week lag rule), never a per-record publication receipt; that is stated on every affected cell.

## Per-season coverage (fitting corpora and extended seasons)

| Season | Team-games | Starter identified % | Prior-game snaps complete % | QB designation determinable % | QB reserve determinable % | QB2 (prior-wk chart) % | S3+S5 combined % | Backup starts | Q cases (QB) | Cross-check S3×S5 consistent % |
|---|---|---|---|---|---|---|---|---|---|---|
| 2012 | 512 | 0.00 | 0.00 | 0.00 | 0.00 | 93.75 | 0.00 | 0 | 0 | 92.67 |
| 2013 | 512 | 100.00 | 93.75 | 83.79 | 83.79 | 93.36 | 83.79 | 43 | 4 | 66.51 |
| 2014 | 512 | 99.80 | 100.00 | 89.84 | 89.84 | 87.30 | 89.84 | 51 | 12 | 69.71 |
| 2015 | 512 | 100.00 | 100.00 | 94.14 | 94.14 | 93.16 | 94.14 | 64 | 10 | 62.14 |
| 2016 | 512 | 100.00 | 100.00 | 95.70 | 95.70 | 93.75 | 95.70 | 56 | 13 | 99.55 |
| 2017 | 512 | 100.00 | 100.00 | 95.12 | 95.31 | 93.75 | 95.12 | 56 | 12 | 99.80 |
| 2018 | 512 | 99.80 | 100.00 | 96.29 | 96.29 | 93.36 | 96.29 | 47 | 13 | 99.77 |
| 2019 | 512 | 99.61 | 100.00 | 92.58 | 92.58 | 92.58 | 92.58 | 54 | 15 | 99.75 |
| 2020 | 512 | 100.00 | 100.00 | 98.05 | 98.24 | 93.55 | 98.05 | 68 | 15 | 99.25 |
| 2021 | 544 | 100.00 | 99.63 | 98.16 | 98.16 | 93.01 | 98.16 | 84 | 16 | 99.52 |
| 2022 | 542 | 99.63 | 100.00 | 90.41 | 90.96 | 92.44 | 90.41 | 77 | 18 | 99.72 |
| 2023 | 544 | 99.82 | 100.00 | 96.32 | 96.51 | 92.83 | 96.32 | 71 | 21 | 97.74 |
| 2024 | 544 | 100.00 | 100.00 | 99.45 | 99.63 | 90.81 | 99.45 | 72 | 14 | 97.38 |

Availability class by signal (all measured seasons): S1/S2 = Retrospective (post-game actuals; the source carries no timestamps). S3/S4/S5/S6 = Historical under cadence-inferred rules. S7/S8 = Forward-capture only (0 historical records, by design). 2012 snaps = Unavailable (source file header-only — see Findings).

## Preregistration §8 gates — measured

### primary_fitting_2019_2024

- gate_s3_s5_qb_coverage_ge_95pct: **95.84** vs threshold 95.0 → PASS
- gate_s2_snap_completeness_ge_95pct: **99.94** vs threshold 95.0 → PASS
- gate_backup_start_games_ge_150: **426** vs threshold 150 → PASS
- gate_questionable_qb_cases_ge_100: **99** vs threshold 100 → FAIL

### extended_2012_2018

- gate_s3_s5_qb_coverage_ge_95pct: **79.27** vs threshold 95.0 → FAIL
- gate_s2_snap_completeness_ge_95pct: **84.82** vs threshold 95.0 → FAIL
- gate_backup_start_games_ge_150: **317** vs threshold 150 → PASS
- gate_questionable_qb_cases_ge_100: **64** vs threshold 100 → FAIL

### all_2012_2024

- gate_s3_s5_qb_coverage_ge_95pct: **87.08** vs threshold 95.0 → FAIL
- gate_s2_snap_completeness_ge_95pct: **91.95** vs threshold 95.0 → FAIL
- gate_backup_start_games_ge_150: **743** vs threshold 150 → PASS
- gate_questionable_qb_cases_ge_100: **163** vs threshold 100 → PASS

## Feasibility verdicts for V2's proposed inputs

| Input | Verdict | Measured % | Basis / restrictions |
|---|---|---|---|
| primary_qb_id (S1/S2) | FEASIBLE | 99.84 | starter identification rate, fitting corpora pooled; snap-derived starter (max offensive snaps); ties fail closed; 2012 unavailable at the named source (header-only file), so extended corpora effectively start 2013 |
| qb_designation (S3) | FEASIBLE | 95.84 | determinable = report row present (any status) or team-week present in the injuries file; final-report cadence rule (cadence-inferred timing, no per-record publication receipt); no revision history; strict explicit-designation rows are a minority of team-games because healthy QBs carry no designation |
| qb_reserve (S5) | FEASIBLE | 96.03 | primary QB found in a prior-week roster snapshot; prior-week lag rule strictly applied (Week 1 team-games uncovered); reserve subtype unresolved (opaque status_description_abbr codes, no codebook) |
| qb_practice_final (S4) | FEASIBLE_WITH_NAMED_RESTRICTIONS | — | practice_status presence among injury-report rows (see per-season S4 counts); weekly snapshot only; per-day progression not reconstructible; optional feature -- drop at design freeze if its value cannot be isolated (foundation S4) |
| backup_qb_id (S1/S6) | FEASIBLE | 92.53 | prior-week depth-chart QB2 identified rate; snap evidence (most recent fill-in starter) outranks the chart; chart snapshot day inside the week is untimestamped; lag rule mandatory |
| absent_share_off/def (S2 x S3/S5) | FEASIBLE | 99.94 | prior-game snap completeness gate metric; trailing shares from completed games only, under the completion-window safeguard; same-game snaps never features |
| game_day_inactives (S7) | NOT_FEASIBLE | 0.0 | no trustworthy timestamped historical archive exists; forward-capture only; excluded from V2 per the parity rule and the owner's decision |
| report_revisions (S8) | NOT_FEASIBLE | 0.0 | no structured timestamped historical archive exists; forward-capture only; excluded from V2 |

## Per-season rejection accounting (fail-closed reasons)

### 2012 (denominator 512 team-games)

- S1_STARTER_ACTUAL [Unavailable]: SOURCE_FILE_EMPTY=512
- S2_SNAP_COUNTS [Unavailable]: SOURCE_FILE_EMPTY=512
- S3_INJURY_DESIGNATIONS [Historical]: PRIMARY_QB_UNDETERMINED=512
- S4_PRACTICE_STATUS [Historical]: CLASS_DNP=1250, CLASS_FP=2520, CLASS_LP=1399, CLASS_OTHER=97, ROWS_TOTAL=5266, ROWS_WITH_PRACTICE_STATUS=5266
- S5_ROSTER_RESERVE [Historical]: PRIMARY_QB_UNDETERMINED=512
- S6_DEPTH_CHARTS [Historical]: QB2_IDENTIFIED_PRIOR_WEEK=480, QB2_NOT_IDENTIFIED=32
- S3×S5 cross-check: reserve player-weeks=2389, consistent=2214 (92.67%), Q/D-while-reserve=175, played-while-reserve=0, reverse Out-but-played=0

### 2013 (denominator 512 team-games)

- S1_STARTER_ACTUAL [Retrospective]: STARTER_IDENTIFIED=512, STARTER_IDENTITY_SCHEDULE_CORROBORATED=52, STARTER_IDENTITY_UNRESOLVED=2
- S2_SNAP_COUNTS [Retrospective]: PRIOR_GAME_SNAPS_COMPLETE=480, SOURCE_FILE_EMPTY=32
- S3_INJURY_DESIGNATIONS [Historical]: PRIMARY_QB_UNDETERMINED=32, QB_IDENTITY_UNRESOLVED_NO_GSIS_BRIDGE=51, QB_NOT_ON_REPORT_TEAM_WEEK_PRESENT=368, QB_ROW_PRESENT=61
- S4_PRACTICE_STATUS [Historical]: CLASS_DNP=1129, CLASS_FP=2360, CLASS_LP=1286, CLASS_OTHER=138, ROWS_TOTAL=4913, ROWS_WITH_PRACTICE_STATUS=4913
- S5_ROSTER_RESERVE [Historical]: PRIMARY_QB_UNDETERMINED=32, QB_FOUND_IN_PRIOR_SNAPSHOT=429, QB_IDENTITY_UNRESOLVED_NO_GSIS_BRIDGE=51, QB_ON_RESERVE_IN_PRIOR_SNAPSHOT=14
- S6_DEPTH_CHARTS [Historical]: QB2_IDENTIFIED_PRIOR_WEEK=478, QB2_NOT_IDENTIFIED=34
- S3 lag evidence (date_modified vs kickoff, UNTRUSTED bookkeeping): n=61, median 56.12h, p10 53.27h, p90 60.27h, min 37.19h; rows modified after kickoff: 0
- S5 effective lag under prior-week rule (days, kickoff minus snapshot bound): n=429, median 4.25, p90 4.56, max 5.56
- S3×S5 cross-check: reserve player-weeks=1878, consistent=1249 (66.51%), Q/D-while-reserve=184, played-while-reserve=483, reverse Out-but-played=0

### 2014 (denominator 512 team-games)

- S1_STARTER_ACTUAL [Retrospective]: STARTER_AMBIGUOUS_TIE=1, STARTER_IDENTIFIED=511, STARTER_IDENTITY_SCHEDULE_CORROBORATED=50, STARTER_IDENTITY_UNRESOLVED=4
- S2_SNAP_COUNTS [Retrospective]: PRIOR_GAME_SNAPS_COMPLETE=512
- S3_INJURY_DESIGNATIONS [Historical]: PRIMARY_QB_UNDETERMINED=1, QB_IDENTITY_UNRESOLVED_NO_GSIS_BRIDGE=51, QB_NOT_ON_REPORT_TEAM_WEEK_PRESENT=388, QB_ROW_PRESENT=72
- S4_PRACTICE_STATUS [Historical]: CLASS_DNP=1328, CLASS_FP=2282, CLASS_LP=1179, CLASS_OTHER=123, ROWS_TOTAL=4912, ROWS_WITH_PRACTICE_STATUS=4912
- S5_ROSTER_RESERVE [Historical]: PRIMARY_QB_UNDETERMINED=1, QB_FOUND_IN_PRIOR_SEASON_SNAPSHOT=30, QB_FOUND_IN_PRIOR_SNAPSHOT=430, QB_IDENTITY_UNRESOLVED_NO_GSIS_BRIDGE=51, QB_ON_RESERVE_IN_PRIOR_SNAPSHOT=28
- S6_DEPTH_CHARTS [Historical]: QB2_IDENTIFIED_PRIOR_WEEK=447, QB2_NOT_IDENTIFIED=65
- S3 lag evidence (date_modified vs kickoff, UNTRUSTED bookkeeping): n=72, median 55.13h, p10 38.36h, p90 60.43h, min 35.59h; rows modified after kickoff: 0
- S5 effective lag under prior-week rule (days, kickoff minus snapshot bound): n=460, median 4.25, p90 5.52, max 251.56
- S3×S5 cross-check: reserve player-weeks=2225, consistent=1551 (69.71%), Q/D-while-reserve=165, played-while-reserve=542, reverse Out-but-played=0

### 2015 (denominator 512 team-games)

- S1_STARTER_ACTUAL [Retrospective]: STARTER_IDENTIFIED=512, STARTER_IDENTITY_SCHEDULE_CORROBORATED=26, STARTER_IDENTITY_UNRESOLVED=4
- S2_SNAP_COUNTS [Retrospective]: PRIOR_GAME_SNAPS_COMPLETE=512
- S3_INJURY_DESIGNATIONS [Historical]: QB_IDENTITY_UNRESOLVED_NO_GSIS_BRIDGE=30, QB_NOT_ON_REPORT_TEAM_WEEK_PRESENT=396, QB_ROW_PRESENT=86
- S4_PRACTICE_STATUS [Historical]: CLASS_DNP=1348, CLASS_FP=2323, CLASS_LP=1284, CLASS_OTHER=54, ROWS_TOTAL=5009, ROWS_WITH_PRACTICE_STATUS=5009
- S5_ROSTER_RESERVE [Historical]: QB_FOUND_IN_PRIOR_SEASON_SNAPSHOT=27, QB_FOUND_IN_PRIOR_SNAPSHOT=455, QB_IDENTITY_UNRESOLVED_NO_GSIS_BRIDGE=30, QB_ON_RESERVE_IN_PRIOR_SNAPSHOT=27
- S6_DEPTH_CHARTS [Historical]: QB2_IDENTIFIED_PRIOR_WEEK=477, QB2_NOT_IDENTIFIED=35
- S3 lag evidence (date_modified vs kickoff, UNTRUSTED bookkeeping): n=86, median 55.05h, p10 49.36h, p90 58.43h, min 36.06h; rows modified after kickoff: 0
- S5 effective lag under prior-week rule (days, kickoff minus snapshot bound): n=482, median 4.25, p90 5.52, max 258.6
- S3×S5 cross-check: reserve player-weeks=2512, consistent=1561 (62.14%), Q/D-while-reserve=221, played-while-reserve=776, reverse Out-but-played=1

### 2016 (denominator 512 team-games)

- S1_STARTER_ACTUAL [Retrospective]: STARTER_IDENTIFIED=512, STARTER_IDENTITY_SCHEDULE_CORROBORATED=18
- S2_SNAP_COUNTS [Retrospective]: PRIOR_GAME_SNAPS_COMPLETE=512
- S3_INJURY_DESIGNATIONS [Historical]: QB_IDENTITY_UNRESOLVED_NO_GSIS_BRIDGE=22, QB_NOT_ON_REPORT_TEAM_WEEK_PRESENT=378, QB_ROW_PRESENT=112
- S4_PRACTICE_STATUS [Historical]: CLASS_DNP=1537, CLASS_FP=2081, CLASS_LP=1310, ROWS_TOTAL=4928, ROWS_WITH_PRACTICE_STATUS=4928
- S5_ROSTER_RESERVE [Historical]: QB_FOUND_IN_PRIOR_SEASON_SNAPSHOT=27, QB_FOUND_IN_PRIOR_SNAPSHOT=463, QB_IDENTITY_UNRESOLVED_NO_GSIS_BRIDGE=22
- S6_DEPTH_CHARTS [Historical]: QB2_IDENTIFIED_PRIOR_WEEK=480, QB2_NOT_IDENTIFIED=32
- S3 lag evidence (date_modified vs kickoff, UNTRUSTED bookkeeping): n=112, median 55.32h, p10 36.4h, p90 61.85h, min 28.14h; rows modified after kickoff: 0
- S5 effective lag under prior-week rule (days, kickoff minus snapshot bound): n=490, median 4.25, p90 11.25, max 251.6
- S3×S5 cross-check: reserve player-weeks=4397, consistent=4377 (99.55%), Q/D-while-reserve=9, played-while-reserve=12, reverse Out-but-played=0

### 2017 (denominator 512 team-games)

- S1_STARTER_ACTUAL [Retrospective]: STARTER_IDENTIFIED=512, STARTER_IDENTITY_SCHEDULE_CORROBORATED=22, STARTER_IDENTITY_UNRESOLVED=2
- S2_SNAP_COUNTS [Retrospective]: PRIOR_GAME_SNAPS_COMPLETE=512
- S3_INJURY_DESIGNATIONS [Historical]: QB_IDENTITY_UNRESOLVED_NO_GSIS_BRIDGE=24, QB_NOT_ON_REPORT_TEAM_WEEK_PRESENT=394, QB_ROW_PRESENT=93, TEAM_WEEK_ABSENT_FROM_SOURCE=1
- S4_PRACTICE_STATUS [Historical]: CLASS_DNP=1386, CLASS_FP=2340, CLASS_LP=1223, ROWS_TOTAL=4949, ROWS_WITH_PRACTICE_STATUS=4949
- S5_ROSTER_RESERVE [Historical]: QB_FOUND_IN_PRIOR_SEASON_SNAPSHOT=31, QB_FOUND_IN_PRIOR_SNAPSHOT=457, QB_IDENTITY_UNRESOLVED_NO_GSIS_BRIDGE=24
- S6_DEPTH_CHARTS [Historical]: QB2_IDENTIFIED_PRIOR_WEEK=480, QB2_NOT_IDENTIFIED=32
- S3 lag evidence (date_modified vs kickoff, UNTRUSTED bookkeeping): n=93, median 54.64h, p10 52.0h, p90 61.2h, min 33.61h; rows modified after kickoff: 0
- S5 effective lag under prior-week rule (days, kickoff minus snapshot bound): n=488, median 4.25, p90 11.25, max 257.21
- S3×S5 cross-check: reserve player-weeks=4613, consistent=4604 (99.8%), Q/D-while-reserve=7, played-while-reserve=2, reverse Out-but-played=0

### 2018 (denominator 512 team-games)

- S1_STARTER_ACTUAL [Retrospective]: STARTER_AMBIGUOUS_TIE=1, STARTER_IDENTIFIED=511, STARTER_IDENTITY_SCHEDULE_CORROBORATED=19
- S2_SNAP_COUNTS [Retrospective]: PRIOR_GAME_SNAPS_COMPLETE=512
- S3_INJURY_DESIGNATIONS [Historical]: PRIMARY_QB_UNDETERMINED=1, QB_IDENTITY_UNRESOLVED_NO_GSIS_BRIDGE=18, QB_NOT_ON_REPORT_TEAM_WEEK_PRESENT=385, QB_ROW_PRESENT=108
- S4_PRACTICE_STATUS [Historical]: CLASS_DNP=1309, CLASS_FP=2401, CLASS_LP=1236, CLASS_OTHER=15, ROWS_TOTAL=4961, ROWS_WITH_PRACTICE_STATUS=4961
- S5_ROSTER_RESERVE [Historical]: PRIMARY_QB_UNDETERMINED=1, QB_FOUND_IN_PRIOR_SEASON_SNAPSHOT=31, QB_FOUND_IN_PRIOR_SNAPSHOT=462, QB_IDENTITY_UNRESOLVED_NO_GSIS_BRIDGE=18
- S6_DEPTH_CHARTS [Historical]: QB2_IDENTIFIED_PRIOR_WEEK=478, QB2_NOT_IDENTIFIED=34
- S3 lag evidence (date_modified vs kickoff, UNTRUSTED bookkeeping): n=108, median 54.62h, p10 51.87h, p90 60.65h, min 29.59h; rows modified after kickoff: 0
- S5 effective lag under prior-week rule (days, kickoff minus snapshot bound): n=493, median 4.25, p90 11.25, max 251.6
- S3×S5 cross-check: reserve player-weeks=4324, consistent=4314 (99.77%), Q/D-while-reserve=10, played-while-reserve=0, reverse Out-but-played=0

### 2019 (denominator 512 team-games)

- S1_STARTER_ACTUAL [Retrospective]: STARTER_AMBIGUOUS_TIE=2, STARTER_IDENTIFIED=510, STARTER_IDENTITY_SCHEDULE_CORROBORATED=32, STARTER_IDENTITY_UNRESOLVED=6
- S2_SNAP_COUNTS [Retrospective]: PRIOR_GAME_SNAPS_COMPLETE=512
- S3_INJURY_DESIGNATIONS [Historical]: PRIMARY_QB_UNDETERMINED=2, QB_IDENTITY_UNRESOLVED_NO_GSIS_BRIDGE=36, QB_NOT_ON_REPORT_TEAM_WEEK_PRESENT=370, QB_ROW_PRESENT=104
- S4_PRACTICE_STATUS [Historical]: CLASS_DNP=1486, CLASS_FP=2433, CLASS_LP=1257, CLASS_OTHER=26, ROWS_TOTAL=5202, ROWS_WITH_PRACTICE_STATUS=5202
- S5_ROSTER_RESERVE [Historical]: PRIMARY_QB_UNDETERMINED=2, QB_FOUND_IN_PRIOR_SEASON_SNAPSHOT=30, QB_FOUND_IN_PRIOR_SNAPSHOT=444, QB_IDENTITY_UNRESOLVED_NO_GSIS_BRIDGE=36
- S6_DEPTH_CHARTS [Historical]: QB2_IDENTIFIED_PRIOR_WEEK=474, QB2_NOT_IDENTIFIED=38
- S3 lag evidence (date_modified vs kickoff, UNTRUSTED bookkeeping): n=104, median 54.65h, p10 51.95h, p90 59.65h, min 29.56h; rows modified after kickoff: 0
- S5 effective lag under prior-week rule (days, kickoff minus snapshot bound): n=474, median 4.25, p90 11.25, max 251.6
- S3×S5 cross-check: reserve player-weeks=4709, consistent=4697 (99.75%), Q/D-while-reserve=7, played-while-reserve=6, reverse Out-but-played=0

### 2020 (denominator 512 team-games)

- S1_STARTER_ACTUAL [Retrospective]: STARTER_IDENTIFIED=512, STARTER_IDENTITY_SCHEDULE_CORROBORATED=5, STARTER_IDENTITY_UNRESOLVED=2
- S2_SNAP_COUNTS [Retrospective]: PRIOR_GAME_SNAPS_COMPLETE=512
- S3_INJURY_DESIGNATIONS [Historical]: QB_IDENTITY_UNRESOLVED_NO_GSIS_BRIDGE=9, QB_NOT_ON_REPORT_TEAM_WEEK_PRESENT=422, QB_ROW_PRESENT=80, TEAM_WEEK_ABSENT_FROM_SOURCE=1
- S4_PRACTICE_STATUS [Historical]: CLASS_DNP=1567, CLASS_FP=2462, CLASS_LP=1356, CLASS_OTHER=29, ROWS_TOTAL=5414, ROWS_WITH_PRACTICE_STATUS=5414
- S5_ROSTER_RESERVE [Historical]: QB_FOUND_IN_PRIOR_SEASON_SNAPSHOT=28, QB_FOUND_IN_PRIOR_SNAPSHOT=475, QB_IDENTITY_UNRESOLVED_NO_GSIS_BRIDGE=9
- S6_DEPTH_CHARTS [Historical]: QB2_IDENTIFIED_PRIOR_WEEK=479, QB2_NOT_IDENTIFIED=33
- S3 lag evidence (date_modified vs kickoff, UNTRUSTED bookkeeping): n=80, median 55.09h, p10 52.69h, p90 61.25h, min 28.95h; rows modified after kickoff: 0
- S5 effective lag under prior-week rule (days, kickoff minus snapshot bound): n=503, median 4.25, p90 10.35, max 258.59
- S3×S5 cross-check: reserve player-weeks=4815, consistent=4779 (99.25%), Q/D-while-reserve=36, played-while-reserve=0, reverse Out-but-played=0

### 2021 (denominator 544 team-games)

- S1_STARTER_ACTUAL [Retrospective]: STARTER_IDENTIFIED=544, STARTER_IDENTITY_SCHEDULE_CORROBORATED=10, STARTER_IDENTITY_UNRESOLVED=1
- S2_SNAP_COUNTS [Retrospective]: PRIOR_GAME_SNAPS_COMPLETE=542, PRIOR_GAME_SNAPS_INCOMPLETE=2
- S3_INJURY_DESIGNATIONS [Historical]: QB_IDENTITY_UNRESOLVED_NO_GSIS_BRIDGE=10, QB_NOT_ON_REPORT_TEAM_WEEK_PRESENT=414, QB_ROW_PRESENT=120
- S4_PRACTICE_STATUS [Historical]: CLASS_DNP=1662, CLASS_FP=2266, CLASS_LP=1377, CLASS_OTHER=43, ROWS_TOTAL=5348, ROWS_WITH_PRACTICE_STATUS=5348
- S5_ROSTER_RESERVE [Historical]: QB_FOUND_IN_PRIOR_SEASON_SNAPSHOT=31, QB_FOUND_IN_PRIOR_SNAPSHOT=503, QB_IDENTITY_UNRESOLVED_NO_GSIS_BRIDGE=10
- S6_DEPTH_CHARTS [Historical]: QB2_IDENTIFIED_PRIOR_WEEK=506, QB2_NOT_IDENTIFIED=38
- S3 lag evidence (date_modified vs kickoff, UNTRUSTED bookkeeping): n=120, median 47.26h, p10 45.0h, p90 53.62h, min 18.67h; rows modified after kickoff: 0
- S5 effective lag under prior-week rule (days, kickoff minus snapshot bound): n=534, median 4.25, p90 11.25, max 251.51
- S3×S5 cross-check: reserve player-weeks=6089, consistent=6060 (99.52%), Q/D-while-reserve=29, played-while-reserve=0, reverse Out-but-played=2

### 2022 (denominator 542 team-games)

- S1_STARTER_ACTUAL [Retrospective]: STARTER_AMBIGUOUS_TIE=2, STARTER_IDENTIFIED=540, STARTER_IDENTITY_SCHEDULE_CORROBORATED=46, STARTER_IDENTITY_UNRESOLVED=6
- S2_SNAP_COUNTS [Retrospective]: PRIOR_GAME_SNAPS_COMPLETE=542
- S3_INJURY_DESIGNATIONS [Historical]: PRIMARY_QB_UNDETERMINED=2, QB_IDENTITY_UNRESOLVED_NO_GSIS_BRIDGE=47, QB_NOT_ON_REPORT_TEAM_WEEK_PRESENT=378, QB_ROW_PRESENT=112, TEAM_WEEK_ABSENT_FROM_SOURCE=3
- S4_PRACTICE_STATUS [Historical]: CLASS_DNP=1700, CLASS_FP=2280, CLASS_LP=1443, CLASS_OTHER=27, ROWS_TOTAL=5450, ROWS_WITH_PRACTICE_STATUS=5450
- S5_ROSTER_RESERVE [Historical]: PRIMARY_QB_UNDETERMINED=2, QB_FOUND_IN_PRIOR_SEASON_SNAPSHOT=30, QB_FOUND_IN_PRIOR_SNAPSHOT=463, QB_IDENTITY_UNRESOLVED_NO_GSIS_BRIDGE=47
- S6_DEPTH_CHARTS [Historical]: QB2_IDENTIFIED_PRIOR_WEEK=501, QB2_NOT_IDENTIFIED=41
- S3 lag evidence (date_modified vs kickoff, UNTRUSTED bookkeeping): n=112, median 46.77h, p10 44.1h, p90 52.51h, min 24.85h; rows modified after kickoff: 0
- S5 effective lag under prior-week rule (days, kickoff minus snapshot bound): n=493, median 4.25, p90 11.25, max 244.51
- S3×S5 cross-check: reserve player-weeks=4979, consistent=4965 (99.72%), Q/D-while-reserve=14, played-while-reserve=0, reverse Out-but-played=0

### 2023 (denominator 544 team-games)

- S1_STARTER_ACTUAL [Retrospective]: STARTER_AMBIGUOUS_TIE=1, STARTER_IDENTIFIED=543, STARTER_IDENTITY_SCHEDULE_CORROBORATED=12, STARTER_IDENTITY_UNRESOLVED=1
- S2_SNAP_COUNTS [Retrospective]: PRIOR_GAME_SNAPS_COMPLETE=544
- S3_INJURY_DESIGNATIONS [Historical]: PRIMARY_QB_UNDETERMINED=1, QB_IDENTITY_UNRESOLVED_NO_GSIS_BRIDGE=18, QB_NOT_ON_REPORT_TEAM_WEEK_PRESENT=429, QB_ROW_PRESENT=95, TEAM_WEEK_ABSENT_FROM_SOURCE=1
- S4_PRACTICE_STATUS [Historical]: CLASS_DNP=1555, CLASS_FP=2448, CLASS_LP=1415, CLASS_OTHER=33, ROWS_TOTAL=5451, ROWS_WITH_PRACTICE_STATUS=5451
- S5_ROSTER_RESERVE [Historical]: PRIMARY_QB_UNDETERMINED=1, QB_FOUND_IN_PRIOR_SEASON_SNAPSHOT=26, QB_FOUND_IN_PRIOR_SNAPSHOT=499, QB_IDENTITY_UNRESOLVED_NO_GSIS_BRIDGE=18
- S6_DEPTH_CHARTS [Historical]: QB2_IDENTIFIED_PRIOR_WEEK=505, QB2_NOT_IDENTIFIED=39
- S3 lag evidence (date_modified vs kickoff, UNTRUSTED bookkeeping): n=95, median 46.95h, p10 44.18h, p90 52.87h, min 28.61h; rows modified after kickoff: 0
- S5 effective lag under prior-week rule (days, kickoff minus snapshot bound): n=525, median 4.25, p90 11.21, max 244.51
- S3×S5 cross-check: reserve player-weeks=4689, consistent=4583 (97.74%), Q/D-while-reserve=106, played-while-reserve=0, reverse Out-but-played=0

### 2024 (denominator 544 team-games)

- S1_STARTER_ACTUAL [Retrospective]: STARTER_IDENTIFIED=544, STARTER_IDENTITY_UNRESOLVED=1
- S2_SNAP_COUNTS [Retrospective]: PRIOR_GAME_SNAPS_COMPLETE=544
- S3_INJURY_DESIGNATIONS [Historical]: QB_IDENTITY_UNRESOLVED_NO_GSIS_BRIDGE=2, QB_NOT_ON_REPORT_TEAM_WEEK_PRESENT=421, QB_ROW_PRESENT=120, TEAM_WEEK_ABSENT_FROM_SOURCE=1
- S4_PRACTICE_STATUS [Historical]: CLASS_DNP=1501, CLASS_FP=2966, CLASS_LP=1450, CLASS_OTHER=37, ROWS_TOTAL=5954, ROWS_WITH_PRACTICE_STATUS=5954
- S5_ROSTER_RESERVE [Historical]: QB_FOUND_IN_PRIOR_SEASON_SNAPSHOT=31, QB_FOUND_IN_PRIOR_SNAPSHOT=511, QB_IDENTITY_UNRESOLVED_NO_GSIS_BRIDGE=2
- S6_DEPTH_CHARTS [Historical]: QB2_IDENTIFIED_PRIOR_WEEK=494, QB2_NOT_IDENTIFIED=50
- S3 lag evidence (date_modified vs kickoff, UNTRUSTED bookkeeping): n=120, median 47.49h, p10 44.98h, p90 53.42h, min 22.99h; rows modified after kickoff: 0
- S5 effective lag under prior-week rule (days, kickoff minus snapshot bound): n=542, median 4.25, p90 11.25, max 244.51
- S3×S5 cross-check: reserve player-weeks=5184, consistent=5048 (97.38%), Q/D-while-reserve=136, played-while-reserve=0, reverse Out-but-played=1


## Findings — where the measured data contradicts or sharpens the design doc

1. **2012 snap counts do not exist at the named source.** The foundation
   doc (and nflreadr documentation) dates PFR snap counts from 2012, but
   the nflverse release file `snap_counts_2012.csv` is header-only
   (154 bytes, zero rows) and the parquet twin is an empty shell
   (~4.6 KB). Measured consequence: every snap-dependent cell for 2012 is
   UNAVAILABLE (reason SOURCE_FILE_EMPTY), and the hole leaks into early
   2013 (prior games in 2012), where S2 completeness measures 93.75% and
   32 Week-1 team-games have undeterminable primaries. The extended
   fitting corpus effectively starts **2013**, not 2012. (PFR's own site
   carries 2012 snaps; the doc's named release path does not. Closing
   this would require a different source and a new availability audit.)

2. **The binding constraint on QB coverage is identity resolution, not
   data availability.** In every measured season the dominant rejection
   for both S3 and S5 is `QB_IDENTITY_UNRESOLVED_NO_GSIS_BRIDGE`:
   pooled across 2019–2024 it accounts for 122 of the ~133 uncovered
   team-games (per-season range 2–47, worst in 2019/2022, shrinking to
   2 by 2024). The mechanism: the snap file keys
   players by PFR id, the roster file's `pfr_id` column is **blank** for
   exactly the affected players (verified by name: e.g. Jake Browning,
   Tim Boyle, Case Keenum have 17–19 roster rows each with gsis present
   and pfr_id empty). Where identity resolves, designation determinability
   and roster determinability are near-total (team-weeks are present in
   the injuries file in effectively all team-games; starting QBs are on
   prior snapshots). A foundation that cannot name its primary QB cannot
   score the team-game — fail-closed accounting puts those team-games in
   the uncovered bucket, which is why the combined gate clears 95% only
   narrowly (95.84%).

3. **The Questionable-case estimator gate fails by one case — and it is
   the bridge's fault.** Strict bridge, 2019–2024 pooled: **99**
   Questionable primary-QB cases vs the preregistration §8 threshold of
   100 → gate FAIL. Under the schedule-corroborated bridge (below), the
   same seasons yield **105** → pass, and combined coverage rises to
   99.12%. The shortfall is an identity artifact, not missing injury
   data.

4. **Schedule-corroborated identity recovery (sensitivity, not
   headline).** For ~90% of bridge-failed starters, the schedule's listed
   QB (games.csv, an independent pipeline) has the identical name for the
   same game/team — e.g. 2013: 52 corroborated vs 2 unresolved; 2022: 46
   vs 6. The headline metrics deliberately do NOT use this: name matching
   has caused production identity incidents in this project. Whether the
   corroborated bridge (exact name equality + game/team binding + GSIS
   taken from the schedule, never from the name) is admissible is an
   **owner decision at lock time**. Full sensitivity numbers are in the
   JSON (`sensitivity_schedule_corroborated_bridge`).

5. **The doc's "designation row" framing understates how injury reports
   work.** Strict explicit-designation rows (O/D/Q) exist for only
   15–22% of primary-QB team-games, because a healthy QB carries no
   designation. The honest coverage metric is *determinability* (row
   present with any status, or team-week present and QB not reported =
   no designation). Both are reported per season; the §8 gate is judged
   on determinability. Anyone quoting the strict number as "coverage"
   would be mismeasuring the source.

6. **Early-era roster files (2012–2015) contain conflicting duplicate
   player-week rows** (~1,200–1,900 per season, vanishing from 2016).
   The collector keeps the first occurrence and counts conflicts
   (`DUPLICATE_CONFLICTING_VALUES`); the coverage index uses the same
   first-wins rule. Early-era cross-check consistency is also far worse
   (2013: 66.5%, 2015: 62.1% vs 97–99.8% from 2016 on) — driven by
   designation-while-reserve conflicts in the older files. Extended-era
   pooling for anything except the QB-delta sample should be treated
   with era skepticism; the doc's "2012–2018 usable" estimate is
   optimistic for S3×S5-sensitive uses.

7. **Reserve subtype is genuinely unresolved.** Weekly-roster `status`
   gives the RES bucket, but the subtype rides on opaque
   `status_description_abbr` codes (R01, R04, …) with no in-file
   codebook. The foundation can prove "on a reserve list" — which is
   what the availability state machine needs (OUT, probability 1) — but
   cannot distinguish IR-return designations from season-ending IR from
   this file alone. The doc anticipated verifying a transactions loader
   at build time; nflverse's release set used here has no dated
   transactions file with placement/return dates, so transaction-date
   precision remains an open gap (the day-granularity roster rule is
   what stands).

8. **S3 lag evidence supports the cadence rule.** For primary-QB report
   rows, the (untrusted) `date_modified` bookkeeping timestamp sits a
   median of 47–55 hours before kickoff across the six fitting seasons
   (seasonal minimums 19–30h) with zero post-kickoff modifications in
   any of them — consistent with the
   Friday-final-report cadence for Sunday games. This is corroboration
   of the cadence inference, not a publication receipt, and the cells
   stay classified CADENCE_INFERRED.

9. **S5 effective lag under the prior-week rule is real but bounded:**
   median ≈ 4.3 days from snapshot bound to kickoff, p90 ≈ 5.5 days,
   max ≈ 12.6 days (bye-week cases). V2 as designed is a day-before
   model; the roster leg is a ~4-day-old fact by construction, which is
   the honest cost of the lag rule.

## What remains before the foundation can support a preregistration lock

1. **Owner decision: identity bridge.** Adopt or reject the
   schedule-corroborated bridge (§4 above). It decides whether the §8
   Questionable gate passes (105) or fails (99) on the 2019–2024
   fitting corpora, and moves combined QB coverage 95.84% → 99.12%.
2. **Era bound for fitting corpora** must be chosen at lock with these
   measurements in view: 2019–2024 passes three of four gates (Q-case
   gate per item 1); pooled 2012–2024 passes the sample gates but the
   S3/S5 and S2 coverage gates fail on early-era data quality (2012
   hole, 2013–2015 conflicts). A 2016+ or 2019+ era is the defensible
   reading of the measurements.
3. **Transactions source** for dated IR placement/return (item 7) if
   subtype precision is ever required; not required for the OUT rule.
4. **Forward capture must actually start running** (injury reports per
   publication day, Saturday changes, T-90 inactives) so the prospective
   window's contemporaneous evidence exists; the schema and reader
   support it today, but no capture has been collected yet, and the
   selected window's §8 coverage gates can only be measured from
   captures as they accrue.
5. The 2025 season was **not** measured and must not be added to any
   fitting corpus (owner rejection per the contamination audit); the
   selected prospective window's coverage will be measured from forward
   capture, not from these historical files.

## Archive and code

- Package: `sportsedge/participation/` (branch
  `feat/nfl-participation-foundation-20261012`) — schema, append-only
  archive, as-of reader, collectors, coverage measurement.
- Populated archive (local worktree, not committed — payloads are
  re-downloadable and receipts carry their SHAs):
  1,004,996 records, 53 raw payloads hash-verified, 52 collector
  receipts, integrity check clean.
- Machine-readable coverage: `sportsedge/participation/coverage_measured.json`.
- Tests: 23 passed (schema honesty rules, archive immutability,
  reader lag rules / same-game-snap refusal, collector parsing on
  recorded real payload subsets, no network).
