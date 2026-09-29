# Sept. 29 MLB context-adjusted research rerun

Status: **NOT Model_P · NOT Truth Gate · NOT OFFICIAL**

Workflow: `mlb-context-adjusted-research` has completed the live-slate rerun and a retrospective diagnostic validation. This lane does not modify the production registry, promotion evidence, staking, or OFFICIAL authority.

## What changed

The production manual full-game path uses each club's own last-30 runs scored as `away_mean_runs` / `home_mean_runs`. Pregame context is acquired only after pricing and is explicitly `model_p_eligible=false`.

The research lane instead:

- blends each offense's last-30 runs scored 50/50 with the opponent's last-30 runs allowed;
- tests the current probable starter's strictly-prior starts as an adjustment to the expected share of the game represented by that starter's recent mean outs;
- consumes NWS/roof context before simulation on the live slate;
- applies no outdoor temperature adjustment when retractable-roof state is unknown;
- treats 60–83 F as the neutral temperature band; the cold/warm sensitivity remains research-only and is not promotion evidence;
- sends the adjusted means through the existing shared SportsEdge full-game distribution.

## Sept. 29 live-slate diagnostic

The context-fed rerun materially reduced the prior all-over shape. Examples:

| Previous displayed selection | Previous | Research | Change |
|---|---:|---:|---:|
| White Sox ML +102 | 57.3% | 39.7% | -17.6 pts |
| White Sox TT O3.5 -135 | 72.2% | 50.6% | -21.6 pts |
| Astros TT O3.5 -145 | 63.3% | 63.9% | +0.6 pts |
| CHW/HOU O8 -118 | 65.2% | 48.3% | -16.9 pts |
| Yankees TT O3.5 +114 | 76.2% | 55.5% | -20.7 pts |
| Yankees -1.5 +159 | 57.9% | 47.5% | -10.4 pts |
| Yankees ML -140 | 78.5% | 72.8% | -5.7 pts |
| Red Sox TT O2.5 -125 | 57.3% | 44.8% | -12.5 pts |
| BOS/NYY O6 -116 | 78.5% | 53.0% | -25.5 pts |
| CHC/SD O7.5 +100 | 80.7% | 57.0% | -23.7 pts |
| Cubs TT O3.5 -110 | 77.1% | 55.8% | -21.3 pts |
| Padres TT O3.5 -115 | 76.2% | 63.8% | -12.4 pts |
| Cubs ML +103 | 51.3% | 43.6% | -7.7 pts |

That proves the old card was highly sensitive to the offense-only run baseline. It does **not** prove that the full starter/weather transform is calibrated.

## Retrospective holdout diagnostic: Sept. 1–14, 2026

Workflow run `36623832704` completed successfully. It evaluated 186 final regular-season games with 3,000 deterministic simulation paths per game/model. There were zero skipped games. Three versions were compared on the same games: offense-only, 50/50 offense/opponent-defense blend, and the full starter adjustment with weather held neutral.

| Version | Binary Brier | Binary log loss | ECE | Total RMSE | Total MAE | Total mean error |
|---|---:|---:|---:|---:|---:|---:|
| Offense only | 0.2413 | 0.6802 | 0.0710 | 4.8123 | 3.6871 | -0.7344 |
| Defense blend | **0.2329** | **0.6601** | **0.0552** | **4.7160** | **3.6336** | -0.7349 |
| Starter adjusted | 0.2480 | 0.6969 | 0.0919 | 4.8974 | 3.8125 | -1.0947 |

On this diagnostic window, the defense blend improved all three binary calibration/error metrics and total-run RMSE/MAE versus offense-only. The full starter transform then gave those gains back and was worse than both alternatives. It shifted the average predicted total down from 8.889 runs to 8.529 while the observed average was 9.624, increasing underprediction.

The game-total over thresholds tell the same story. For the starter-adjusted version, mean predicted over probabilities vs observed frequencies were 75.1% vs 76.3% at 6.5, 60.8% vs 62.9% at 7.5, 51.3% vs 56.5% at 8.5, and 37.2% vs 47.8% at 9.5. The current starter adjustment is therefore **not promotion-ready** and should not be used to manufacture smaller edges simply because it fixes the Sept. 29 card aesthetically.

## Evidence limits

This validation is deliberately `DIAGNOSTIC_ONLY_PIT_EVIDENCE_INCOMPLETE`:

- the historical probable-pitcher identities come from the current historical StatsAPI schedule field and are not archived proof of what was known at the original betting decision time;
- the repository still lacks a historical point-in-time NWS forecast archive;
- historical game-day retractable-roof state is not archived;
- weather was therefore held neutral in the retrospective validation rather than leaked from postgame observations;
- 31 of 33 starters per side were available in the initial three-day smoke test; in the 186-game window, 175 away and 177 home starters had sufficient strict-prior starts, with the rest failing neutral.

## Current decision

Keep the 50/50 offense/opponent-defense blend as the leading research candidate. Do **not** promote the current full-strength starter multiplier. Until a starter transform passes a separate chronological train/holdout test, pitcher information must remain labeled **context only** in public-facing output. Weather may affect the research run only when sourced before simulation and outdoor exposure is verified, but it also remains non-Model_P until historical PIT forecast/roof evidence is available.

Public card output remains blocked from using this lane as a final card. The fixed disclosure is:

**NOT Model_P · NOT Truth Gate · NOT OFFICIAL**

Lineups/umpire confirmation status must be shown when not confirmed, ML/RL rows remain withheld while their deployment blockers are unresolved, and correlated rows must be grouped rather than presented as independent edges.
