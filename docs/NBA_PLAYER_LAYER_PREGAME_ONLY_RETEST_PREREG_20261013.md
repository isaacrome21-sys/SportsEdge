# Pre-registration: NBA player layer, pregame-only retest (2026-27)

Committed **before** any code for this experiment is written and before any 2026-27 NBA outcome or injury report is fetched by this lane. Docs only: no code, no data.

**Governance flag:** new pre-registration path; it needs ChatGPT freeze-inventory registration (`config/reconciliation_coverage_v1.json`) before `main-merge-hold` can pass. Research only. No promotion, no PLAY, no WATCH upgrade, no betting eligibility under any outcome. Market baseline MISSING; any line used is a naive stand-in.

## Why
Every earlier player-layer test on #2147 (v1, v2, v2 fair retest, v3 controlled) used a RETROSPECTIVE_AVAILABILITY_ORACLE: both arms knew who actually played and/or their actual minutes. Those results say nothing about pregame value. This test allows only information that existed before a fixed cutoff ahead of tip.

## Disclosure
- 2024-25 and 2025-26 player-games were used by v1–v3 and are contaminated for evaluation. They may be used only to fit frozen parameters (below).
- **2026-27 regular season is the only evaluation season.**

## Information cutoff (frozen)
- `T_cut = scheduled tip − 90 minutes` (official schedule tip time, UTC).
- An input is admissible only if its publication time is provably `≤ T_cut`. If publication time cannot be established, the input is treated as **absent**, never as present.
- Forbidden for both arms: actual minutes, actual starters, box-score participation, DNP flags, any injury report published after `T_cut`, any post-game data.

## Data sources (frozen)
1. **Official NBA injury report** (the league's published report PDFs, timestamped by report time). Use the latest report with report time `≤ T_cut`. Status mapping: OUT → 0 expected minutes; DOUBTFUL → 0.25 × baseline; QUESTIONABLE → 0.5 × baseline; PROBABLE / not listed → baseline.
2. **Projected starters:** only if a source with a verifiable pre-`T_cut` timestamp exists. If none, projected starters = the last game's starters among players not OUT. No third-party lineup site whose publish time cannot be verified.
3. **Last-known rotation:** each player's minutes over his team's previous 10 games (games completed before the current game day), EWMA half-life fixed in the fit step.
4. Team ratings: the as-of walk-forward from #2147, unchanged.

**Availability rule:** if official injury reports with report timestamps are not retrievable for ≥ 90% of evaluated games, the result is **INCONCLUSIVE_SOURCE**, with no PASS or FAIL. Reports retrieved later from the public archive are acceptable only because the report time is printed in the official document; this is disclosed, not treated as our own receipt-anchored capture.

## Arms (identical games, seeds, scoring)
- **Comparator — TEAM_ONLY (frozen):** the #2147 team-only model as frozen at head `77105150` (as-of team ratings, frozen quarter calibration, no player layer). For player props, the comparator's player distribution is the naive baseline: last-10 per-game average scaled by the team-only projected pace, Poisson.
- **Challenger — PLAYER_LAYER_PREGAME:** the v3 per-minute model (shrunk rates + player-level NB dispersion), with expected minutes built only from sources 1–3 and renormalized to 240 team minutes. Team strength adjusted only through those pregame minutes.
- Parameters (EWMA half-life, shrinkage, dispersion) are fit on 2024-25 and 2025-26 using the same pregame-only construction, and committed with their fit curves before any 2026-27 outcome is fetched. Then frozen.

## Metrics (frozen)
- **Primary (game level):** moneyline Brier and log-loss, challenger vs comparator.
- **Primary (player level):** Brier on PTS 9.5/14.5/19.5/24.5, REB 3.5/5.5/7.5, AST 2.5/4.5/6.5 over **all** players listed on the pregame roster who were not OUT at `T_cut` (players who then did not play count, with an actual of 0).
- **Secondary:** expected-minutes MAE vs actual minutes; total and spread Brier; calibration slope.
- Uncertainty: paired bootstrap by game, 2,000 resamples, seed 20261013.

## Decision (fixed)
`PASS_RESEARCH` for a stat (or the ML family) iff all hold:
1. challenger Brier < comparator Brier on every line of that stat (ML: Brier and log-loss both lower);
2. the 95% bootstrap interval of the pooled Brier difference lies entirely below 0;
3. expected-minutes MAE beats the last-10 average minutes baseline;
4. ≥ 900 scorable games and the source-availability rule is met.

Otherwise `FAIL`, or `INCONCLUSIVE_SOURCE` / `INCONCLUSIVE_SAMPLE` as defined. One evaluation run after the 2026-27 regular season; no interim looks. All results reported under every outcome. A PASS only justifies a later test against real market prices; it changes nothing about promotion or eligibility.
