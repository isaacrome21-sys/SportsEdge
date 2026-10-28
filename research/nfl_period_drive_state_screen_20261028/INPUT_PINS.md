# NFL_PERIOD_DRIVE_STATE_V2 — design screen input pins

Screen: `research/nfl_period_drive_state_screen_20261028/screen_nfl_period_drive_state_v2.py`
Design: `research/successor_designs_20261028/DESIGN_NFL_PERIOD_DRIVE_STATE_V2.md` (PR #2872, main 956f28a30)
Run date: 2026-10-28 (America/Chicago). All inputs are nflverse public
releases, pulled before the run; sha256 below is over the bytes
actually used. nflverse files are rolling releases: the pin attests
the bytes used, not source stability.

| Input | Source | sha256 | Notes |
|---|---|---|---|
| games.csv.gz (schedules, 7,548 rows) | nflverse `games` release | `e335a852da158eb98f3d2a6f7d753604fba39cee15340b4592af4e81a885a61b` | Same row count as the v1 screen pull; bytes differ from the v1 pull (`1b4ca0c7…`) and the PR #2831 pin (`82b05d70…`) — living-file drift, disclosed per v1 practice. No coin-toss field exists in this file (basis of reading RD-5). |
| play_by_play_2022.parquet | nflverse `pbp` release | `931121d8897779d7944e2a293e92ed8799c8e5cceef84096ac42339003fedc09` | Training + prior-season supplementation only (RD-2/RD-3); 49,434 rows. |
| play_by_play_2023.parquet | nflverse `pbp` release | `bd3484731408def6b0ec93225bba2bd7b2c65769ca707a2b9444d891abdc6776` | Byte-identical to the v1 screen record. 49,665 rows. |
| play_by_play_2024.parquet | nflverse `pbp` release | `3fd2896bc0b911b615142d2f1fabae54a4bbba5ab7b73b28187b118ef8af6a3b` | Byte-identical to the v1 screen record. 49,492 rows. |
| play_by_play_2025.parquet | nflverse `pbp` release | `c6ecedd6d678cc37ed316b23ef84ee1ec6abb69c514bb11868a7ebd5a367df29` | Byte-identical to the v1 screen record. 48,771 rows. |

Panel: the predecessor's period panel, rebuilt by the v1 pack's own
machinery imported unmodified (`research/nfl_activation_20261027/screen_nfl_activation_v1.py`) —
1,632 team-games, 2023–2025 regular season. Panel integrity is
re-run, not assumed (results in SCREEN_REPORT.md).

Frozen sibling (read-only inputs, never modified):
`NFL_TEAM_TOTAL_DIST_V1` — engine `sportsedge/nfl_team_total_dist.py`,
runner `sportsedge/nfl_team_total_runner.py`, prereg + config on main
at 956f28a30. This branch's diff against main adds only the files of
this screen pack; the sibling's bytes are untouched.
