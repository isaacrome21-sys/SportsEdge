# DraftKings Line Archive Index

Timestamped line captures for forward-test scoring against our own captured lines. Scope per issue #2406: NBA only this week; player props limited to points / rebounds / assists / PRA.

| Date | Capture time (CT) | Sport | Games | Rows | Status | File |
|---|---|---|---|---|---|---|
| 2026-10-19 | 10:53 | NBA | 0 | 0 | CAPTURE_FAILED — DraftKings unreachable (geo/IP block; API 403; board did not render) after two genuine attempts; board existence unknown, no lines captured or fabricated | ~/workspace/sportsedge/dk_line_archive/nba/2026-10-19/1053_ct.json |
| 2026-10-19 | 11:54 | NBA | 14 | 582 | MANUAL_CAPTURE (owner-directed, via main browser) — covers Tue Oct 20 (3) + Wed Oct 21 (11) boards; no games Mon Oct 19 (NO_BOARD today); team totals not displayed on league board | ~/workspace/sportsedge/dk_line_archive/nba/2026-10-19/1154_ct.json |
| 2026-10-19 | 17:21 | NBA | 3 | 158 | CAPTURED (evening, scheduled job) — signed-out board rendered fully; no games Mon Oct 19 (NO_BOARD today); all 3 games are Tue Oct 20; game lines + team totals (from Team Props tabs) + 143 PTS/REB/AST/PRA prop rows, each with its per-section capture timestamp | ~/workspace/sportsedge/dk_line_archive/nba/2026-10-19/1721_ct.json |
2026-10-20 | 05:37 CT | NBA | 6 of 14 games (board lines; PARTIAL — bot wall + geo-denied retry; today's 3 games NOT in this file, freshest complete = 2026-10-19 1721_ct) | dk_line_archive/nba/2026-10-20/0537_ct.json
2026-10-20 | 05:47 CT | CFB | 3 games, 18 rows (game lines only; BLOCKED / FAMILY_REGISTRY_NOT_VALIDATED price record) | dk_line_archive/cfb/2026-10-20/0547_ct.json
2026-10-20 | 05:49 CT | NHL | 11 games, 66 rows (game lines only; PARKED price record) | dk_line_archive/nhl/2026-10-20/0549_ct.json
2026-10-20 | 10:23 CT | NBA | 14 games, 619 rows (CAPTURED, scheduled AM job — attempt 1, no reloads; Oct 20 + Oct 21 boards; game lines + team totals + 549 PTS/REB/AST/PRA props) | dk_line_archive/nba/2026-10-20/1023_ct.json
2026-10-20 | 17:22 CT | NBA | 13 games, 557 rows (CAPTURED, scheduled PM job — attempt 1, no reloads; Oct 20 + Oct 21 boards; game lines + team totals + 492 PTS/REB/AST/PRA props) | dk_line_archive/nba/2026-10-20/1722_ct.json
