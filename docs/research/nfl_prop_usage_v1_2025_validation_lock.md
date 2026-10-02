# NFL prop usage V1 — 2025 one-look validation lock

This lock binds the already-completed 2021–2024 fit from PR #1348 to the
strict pre-kick source audit from PR #1338. It opens no 2025 player outcomes.

The validation cohort is the intersection of:

- DraftKings last-pre-kick paired O/U rows with 0 < lead <= 15 minutes;
- 2025 regular-season games whose official NFL.com inactive article had its
  final Updated/Published timestamp at or before kickoff and contained both
  recognized team inactive sections;
- players not present on the official inactive list;
- the latest nflverse depth snapshot at or before kickoff (unique rank-1 QB
  for QB rows; skill player present for RB/FB/WR/TE rows);
- the frozen V1 model's normal PIT requirements: at least three same-season
  prior appearances and an available Attempt-9 team environment.

Missing or ambiguous evidence emits zero model rows. No rows are filled from
retrospective gamebooks, weekly roster status, participation, or outcomes.

The already-frozen gates are not changed. For passing, rushing and receiving
yards separately and pooled, |mean predicted P(over) - observed over rate|
must be <= 0.06. Candidate pooled Brier must not exceed the development-only
position/market baseline pooled Brier. The zero-row inactive-evidence rule
must hold. All gates are required.

The original prelock did not establish a minimum validation n, so this lock
reports sample sizes but does not invent a post-source support threshold.

Once the one-look runner opens 2025 outcomes, the window is spent regardless
of PASS or FAIL. No V1 retuning or second 2025 look is allowed.
