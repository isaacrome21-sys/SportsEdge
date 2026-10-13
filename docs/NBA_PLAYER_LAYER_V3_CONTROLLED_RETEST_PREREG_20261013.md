# Pre-registration: NBA player layer v3 controlled re-test (identical played-player set and normalization)

Committed before v3 was run. **Governance flag:** this is a new pre-registration path and needs ChatGPT freeze-inventory registration. Research only. Availability is a RETROSPECTIVE_AVAILABILITY_ORACLE for both sides. Props stay WATCH/BLOCKED; market baseline MISSING.

## Why
ChatGPT's review of the fair re-test: the two models normalized minutes over different player groups.
- The candidate used players from the last-10 team games who played the target game.
- The naive baseline used every target-game participant with any history.

## Controlled design (fixed)
- Per team-game, the shared set **S** is the players who (a) appear in the candidate rotation pool (any of the team's last 10 trainable games) and (b) played the target game.
- **Both sides** get raw minutes = the mean over the player's last 10 played trainable games, and both normalize Σ over S to 240.
  - The candidate's rotation is built with exactly S AVAILABLE (all others OUT, `minutes_mode="played"`).
  - The naive side is scaled by 240/Σ_S raw.
- The scored population is the identical set for both sides: players in S with ≥ 3 history games.
- Consequence, stated in advance: the expected minutes are identical by construction, so **the minutes comparison is expected to tie and therefore FAIL** under the strict rule. This is a control check (|ΔMAE| must be < 0.01, else the harness is wrong).
- Stats differ only in the per-minute model: candidate shrunk per-minute rates × minutes with player-level NB dispersion (v2 `player_marginal`), versus naive scaled last-10 mean with Poisson.

## Unchanged
- Data, cohort, PIT (start + 4h proxy), lines, metrics (Brier per line).
- Decision rule: PASS_RESEARCH per stat iff candidate Brier < naive at every line.
- Same 2024-25 cohort that was already used (disclosed reuse; this is a confirmatory control, not fresh validation).
