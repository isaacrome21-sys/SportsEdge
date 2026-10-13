# Pre-registration: CBB as-of ratings v2, fresh-season holdout on 2025-26

This doc was committed **before** any 2025-26 CBB data was fetched.

**Governance flag:** this is a new pre-registration path and needs ChatGPT freeze-inventory registration. It is research only. Lines are NAIVE_STANDIN, and the market baseline is MISSING. The Illinois ESPN-ID exclusion is unchanged, and Illinois games are never evaluated.

## Why it is fresh
v2 was designed and examined only on 2024-25. This lane has never loaded 2025-26 CBB.

## Frozen
- **Code:** exactly as at `a19f7d7` (`asof_ratings.py`, `asof_harness.py`, `run_cbb_asof_harness.py`, version `v2`, `d1` subset). There is no change, tuning, or carry-over of 2024-25 fits; the walk-forward starts cold, self-contained in 2025-26.
- **D1 directory:** the same `d1_teams.json` (ESPN `groups=50`, identity only), copied unchanged. This has the same 2026-directory caveat as before. It is closer in time for 2025-26, though still not an as-of directory.

## Data
- Free ESPN `scoreboard` (`groups=50`) and `summary`, 2025-11-03 through 2026-03-15. That is the same window convention as 2024-25 (season opener to Selection Sunday).
- The same fetch script is used, with only the date range and cache directory (`/workspace/cbb_cache_2025_26`, outside the repo) changed.

## Decision rule (fixed, identical to v2)
- PASS_RESEARCH iff model Brier < naive for moneyline, spread and total, **and** moneyline log-loss < naive.
- Otherwise FAIL. The result is reported in full regardless of outcome. There is no promotion and no PLAY.
