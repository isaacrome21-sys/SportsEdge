# Pre-registration: NBA player layer v2 (minutes fix + player-level dispersion)

Committed before any v2 code was run on data. **Governance flag:** this is a new pre-registration path and needs ChatGPT freeze-inventory registration. Research only. Props stay WATCH/BLOCKED. Market baseline MISSING.

## Motivation
v1 (`NBA_PLAYER_LAYER_PREREG_20261013.md`, result FAIL) had two problems:
- it counted missed recent games as 0 minutes;
- it took per-player variance from the team-total/multinomial split.

## Changes (fixed; no free parameters chosen after seeing data)
1. **Minutes:** a player's expected minutes = his mean minutes over his last 10 trainable games **played** (DNP/inactive excluded, not counted as 0). OUT players get 0. Minutes are then renormalized to 240 per team, as in v1, to keep team coherence.
2. **Rates:** per-minute PTS/REB/AST unchanged from v1 (career-to-date within season, shrink 3 minutes toward the team rate).
3. **Dispersion:** player-level. For stat X, mean μ = rate × expected minutes.
   - Variance V = (n·s² + 3·μ)/(n + 3), where s² is the sample variance of X over his last n ≤ 10 trainable games played.
   - P(X > line) comes from a negative binomial with mean μ and variance V (Poisson if V ≤ μ).
   - These are marginals. The path-coherent allocation (`allocate`) is unchanged for joint use but is not used for v2 marginals.

## Unchanged from v1
- Data and cache.
- Point in time: cutoff = earliest tip on the America/Chicago slate date; training requires start + 4h ≤ cutoff.
- RETROSPECTIVE_AVAILABILITY_ORACLE caveat (look-ahead on who plays).
- Population, fixed lines (PTS 9.5/14.5/19.5/24.5; REB 3.5/5.5/7.5; AST 2.5/4.5/6.5).
- Naive baseline (last-10-played mean, Poisson tail; minutes = last-10-played mean).
- Metrics: Brier per line, minutes MAE.

## Decision rule (fixed)
- Per stat: PASS_RESEARCH iff v2 Brier < naive at every line. Minutes: PASS iff v2 MAE < naive MAE.
- Otherwise FAIL. No tuning after results. Reported alongside v1.
