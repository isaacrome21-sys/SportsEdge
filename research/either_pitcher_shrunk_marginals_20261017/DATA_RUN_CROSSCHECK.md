# Cross-check: complete staging run 39027576218

Run 39027576218 (after the cancelled-game completeness fix `1a75eb98`) reports COMPLETE for 2024, 2025 and 2026.
Its pitching_gamelogs bundles differ in file SHA-256 from run 39026089063 only because retrieval timestamps differ:

| Season | URLs (both runs) | payload sha256 differences |
|---|---|---|
| 2024 | 803 | 0 |
| 2025 | 803 | 0 |
| 2026 | 839 | 0 |

Re-running `eval_either_pitcher_shrunk.py` on run 39027576218's bundles
(`84da0aa2…d0d7`, `5ac5ab86…50b0`, `db7fe99f…e9a7`) gives identical `test_2026`,
`design_descriptive` and `population` sections. The verdicts in REPORT.md stand unchanged on the COMPLETE data.
