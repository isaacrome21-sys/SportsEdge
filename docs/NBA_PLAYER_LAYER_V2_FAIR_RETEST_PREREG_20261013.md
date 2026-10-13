# Pre-registration: NBA player layer v2 fair re-test (oracle-matched naive baseline)

Committed before the re-test was coded or run. **Governance flag:** this is a new pre-registration path and needs ChatGPT freeze-inventory registration. Research only. Props stay WATCH/BLOCKED. Market baseline MISSING.

## Why
The v2 result (`NBA_PLAYER_LAYER_V2_RESULT_20261013.md`) gave v2 the RETROSPECTIVE_AVAILABILITY_ORACLE (who played) but not the naive baseline. This re-test gives both the same after-the-fact knowledge.

## Candidate
v2, exactly as committed (`d6b0662`): played-only minutes, renormalized to 240 over oracle-available players, plus player-level NB marginals. No changes.

## Oracle-matched naive baseline (fixed)
For each target team-game, consider players who actually played (oracle) and have ≥ 1 trainable prior game played:
- raw minutes m_i = mean minutes over his last 10 trainable games played;
- scale c = 240 / Σ m_i over those players; naive minutes = c·m_i;
- naive stat mean = (last-10-played mean of the stat) × c (minutes redistribution applied proportionally);
- P(over) = Poisson tail at that mean.

## Unchanged from v1/v2
- Data and cache.
- PIT rule (start + 4h ≤ slate cutoff, America/Chicago slate date).
- Population, fixed lines, metrics (Brier per line, minutes MAE).

## Decision rule (fixed)
- Per stat: PASS_RESEARCH iff v2 Brier < oracle-naive Brier at every line. Minutes: PASS iff v2 MAE < oracle-naive MAE.
- Otherwise FAIL. Reported alongside the earlier unmatched comparison. No tuning.
