# Pre-registration: CBB v2 vs a shrunk home-court challenger, untouched 2026-27 evaluation

Committed **before** any 2026-27 CBB data is fetched and before any challenger code is written. Authorized by ChatGPT's ruling on #2152 (Oct 13, 2026).

**Governance flag:** new pre-registration path; needs ChatGPT freeze-inventory registration. Research only. Lines are NAIVE_STANDIN; the market baseline is MISSING. No promotion, no PLAY. The Illinois ESPN-ID exclusion (#2148) is unchanged; Illinois games are never evaluated.

## Motivation and disclosure
- v2's jointly fitted home court ended at H = 4.69 (2024-25) and 4.55 (2025-26), above the typical ~3–3.5. Both seasons are already examined, so neither can evaluate a challenger.
- v2 beat its naive baseline on 2025-26 (ML Brier 0.1991 vs 0.2509). It is retained unchanged as the frozen control.

## Arms
- **Control — v2:** code exactly as at `a19f7d7` (`asof_ratings.py`, `asof_harness.py`, `run_cbb_asof_harness.py`, version `v2`, `d1` subset). No changes.
- **Challenger — v2_HCA_SHRUNK:** identical in every respect (same games, same D1 directory, same walk-forward, same team ratings, same `league_pace`/`league_eff`, same `margin_sd` and `total_sd`, same naive lines and scoring) **except** the home-court value used at prediction time:
  - `H_shrunk = 0.5 · H_v2 + 0.5 · 3.0`, where `H_v2` is v2's jointly fitted value at that game's cutoff and 3.0 points is a fixed external prior.
  - Neutral-site games use 0 in both arms, as in v2.
  - Ratings are **not** refit with `H_shrunk`; only the predicted margin and probabilities change. This isolates the home-court effect.
- Shrink weight (0.5) and prior (3.0) are fixed here and will not be tuned.

## Data and window
- Free ESPN `scoreboard` (`groups=50`) and `summary`, same fetch script, from the 2026-27 season opener through Selection Sunday 2027. Walk-forward starts cold in 2026-27, as in the 2025-26 holdout.
- Fetch only after the window closes; one evaluation run; no interim looks; no paid data; no backfill.
- D1-vs-D1 games only are scored; non-D1 games are used in training only, as before.

## Metrics
- **Primary:** moneyline log-loss and spread Brier (home court acts most directly on margin).
- **Secondary:** moneyline Brier, total Brier, mean home-margin residual (actual − predicted) on non-neutral games.
- Paired game-level bootstrap of the challenger − control difference in ML log-loss and spread Brier, 2,000 resamples, seed 20261013.

## Decision (fixed)
`PASS_RESEARCH` (challenger) iff **all** hold:
1. Challenger ML log-loss < control **and** challenger spread Brier < control;
2. the 95% bootstrap interval for at least one primary difference lies entirely below 0, and neither primary interval lies entirely above 0;
3. challenger ML Brier and total Brier are each no worse than control by more than 0.001.

Otherwise `FAIL`, and v2 remains the reference. Under fewer than 3,000 scorable games the result is `INCONCLUSIVE_SAMPLE`. Control vs naive is also reported with the original v2 rule. Results are reported in full under every outcome.

## Schedule-confounding check (diagnostic, not gating)
Purpose: test whether the high H reflects scheduling (strong teams hosting weak non-conference opponents) rather than true home advantage.
- Re-estimate H with v2's joint method on two subsets of 2026-27 games: (a) conference games, where home/away is close to balanced; (b) non-conference games.
- Also report the home-and-home estimate: for team pairs that met once at each venue, half the mean of (home margin in game 1 + home margin in game 2).
- If conference membership is not available from the cached free ESPN payloads, only the home-and-home estimate is reported, and that limitation is stated.
- Reading: a conference/home-and-home H near 3–3.5 alongside a much higher non-conference H supports confounding. The diagnostic informs future research only; it does not change this decision rule.
