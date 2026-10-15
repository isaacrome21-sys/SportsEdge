# Pre-registration: NBA player layer evaluation (2024-25 regular season)

Committed before any player box-score data was fetched or evaluated. **Governance flag:** this is a pre-registration document and a new governance path (the name contains "prereg"). It needs a freeze-inventory mapping from ChatGPT. Research only. Props stay WATCH/BLOCKED (never PLAY). There is no market baseline (MISSING).

## Data
- Free ESPN `summary?event=<id>` box scores (player minutes, PTS, REB, AST) for the 1,234 cached 2024-25 regular-season game IDs, cached outside the repo.
- Team inputs come from the same cache used by the #2147 team harness.

## Point in time
- Cutoff = the earliest tip-off on the target game's slate date (America/Chicago).
- A game trains only if it is FINAL and available by the cutoff, using a conservative buffer: start + 4h ≤ cutoff.

## Availability caveat: RETROSPECTIVE_AVAILABILITY_ORACLE
- No timestamped injury reports exist for 2024-25. In this evaluation, players who logged minutes > 0 in the target game are AVAILABLE and everyone else is OUT.
- **This is look-ahead on availability.** It measures the minutes/rate layer conditional on knowing who plays. It does not measure live performance.
- In production, availability stays UNKNOWN without verified pre-cutoff evidence, so props are BLOCKED.

## Candidate (no free parameters; current #2147 defaults)
- `build_rotation(last_n=10, shrink=3.0)` on trainable logs with oracle availability.
- Team point paths come from `quarter_joint_sim.simulate`, with means from `fit_asof` ratings and calibration from trainable games only. 400 paths, seed = game ID.
- Player probabilities come from `allocate` + `player_market`.
- Minutes = rotation `exp_minutes`.

## Naive baseline
- The player's mean of the stat (and of minutes) over his last 10 trainable games played.
- Over-line probability = Poisson(mean) tail.

## Population
- Target-game players who played (minutes > 0), were in the prior rotation, and have ≥ 3 prior games played.
- Both teams need ≥ 5 trainable games.

## Fixed lines and metrics
- PTS: 9.5, 14.5, 19.5, 24.5
- REB: 3.5, 5.5, 7.5
- AST: 2.5, 4.5, 6.5
- Brier score per line, and minutes MAE.

## Decision rule (fixed)
- Per stat: **PASS_RESEARCH** iff the candidate's Brier < naive at every line of that stat.
- Minutes: PASS iff the candidate's MAE < naive MAE.
- Otherwise FAIL. Single season; no tuning after results; no promotion.
