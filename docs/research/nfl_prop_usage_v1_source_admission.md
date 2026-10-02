# NFL prop usage V1 — source admission

This is the implementation owner that supersedes stale menu-only PR #1250.
It does **not** score the 2025 validation window.

Frozen windows and gates remain unchanged:

- fit/shrink: 2021–2024 regular season;
- one-look validation: 2025 regular season;
- validation markets: passing yards, rushing yards, receiving yards;
- mean absolute probability calibration gap at the posted close line <= 6 pp;
- Brier no worse than the 2021–2024 position-mean baseline;
- zero model rows when the official inactive list or starter identity is unavailable.

Historical line evidence is pinned to a public FanDuel archive at an exact Git
commit. Only identity, line, price, event and timestamp fields are admissible.
If a source row also contains postgame actuals or hit labels, those columns are
not read by the source-admission or model-fit surfaces. The close-line rule is
the latest snapshot strictly before kickoff.

Gameday inactive evidence comes from NFL.com official inactive-report articles.
These are retrospective pages describing a fact that was fixed and announced
before kickoff. Article publication timestamps are not features. The admission
probe must recover every scheduled 2025 regular-season team-game section
(544 team-weeks) before the one-look evaluator is allowed to run.

Starter identity is a separate PIT requirement. Historical validation requires
a depth-chart snapshot at or before target kickoff. Missing or ambiguous
starter evidence emits zero model rows.

This PR is source/data-contract work only. It grants no Model_P, Truth Gate,
OFFICIAL, promotion or staking authority.
