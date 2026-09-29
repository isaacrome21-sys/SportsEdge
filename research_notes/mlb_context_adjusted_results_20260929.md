# Sept. 29 MLB context-adjusted research rerun

Status: **NOT Model_P · NOT Truth Gate · NOT OFFICIAL**

Workflow: `mlb-context-adjusted-research` run 1 (`36621510082`) completed successfully. Five research-guard tests passed before the live-slate rerun. This lane does not modify the production registry, promotion evidence, staking, or OFFICIAL authority.

## What changed

The production manual full-game path uses each club's own last-30 runs scored as `away_mean_runs` / `home_mean_runs`. Pregame context is acquired only after pricing and is explicitly `model_p_eligible=false`.

The research lane instead:

- blends each offense's last-30 runs scored 50/50 with the opponent's last-30 runs allowed;
- uses the current probable starter's strictly-prior starts to adjust only the expected share of the game represented by that starter's recent mean outs;
- consumes NWS/roof context before simulation;
- applies no outdoor temperature adjustment when retractable-roof state is unknown;
- treats 60–83 F as the neutral temperature band; the cold/warm sensitivity remains research-only and is not promotion evidence;
- sends the adjusted means through the existing 100,000-path shared SportsEdge full-game distribution.

## Adjusted run means

| Game | Away mean | Home mean | Total mean | Weather handling | Lineup status at research capture |
|---|---:|---:|---:|---|---|
| White Sox @ Astros | 3.593 | 4.267 | 7.860 | 91 F, retractable roof UNKNOWN → weather not applied | AVAILABLE |
| Red Sox @ Yankees | 2.375 | 3.772 | 6.148 | 67 F open park → neutral temperature band | PARTIAL |
| Cubs @ Padres | 3.843 | 4.287 | 8.131 | 73 F open park → neutral temperature band | MISSING |

Starter evidence used:

- Hagen Smith: only 1 prior start in the strict game-log contract, so starter adjustment failed neutral.
- AJ Blubaugh: 3 prior starts, research ER/9 1.636, mean 11.0 outs.
- Payton Tolle: 12 prior starts, research ER/9 2.898, mean 17.08 outs.
- Cam Schlittler: 12 prior starts, research ER/9 1.528, mean 17.67 outs.
- Matthew Boyd: 12 prior starts, research ER/9 3.737, mean 18.67 outs.
- Michael King: 12 prior starts, research ER/9 3.014, mean 17.92 outs.

## Previous card vs research rerun

Probabilities below use the same selection and, for integer totals, compare conditional win probability excluding pushes.

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

The over inflation shrank materially. Two examples that now change direction at the quoted board are White Sox/Astros O8 (research conditional 48.3%) and Red Sox TT O2.5 (research 44.8%); this demonstrates that the previous all-over card was highly sensitive to the offense-only run baseline.

## Remaining blockers

- This is a diagnostic model change, not calibrated SportsEdge Model_P.
- The starter transform and temperature sensitivity require chronological holdout/calibration before any promotion.
- Wind is not converted to a run multiplier because the run does not yet bind wind direction to verified home-plate/outfield orientation.
- Houston's retractable roof remained UNKNOWN, so outdoor weather was correctly not applied.
- BOS/NYY lineups were only PARTIAL and CHC/SD lineups MISSING at the research capture.
- Public ML/RL presentation remains on hold while the engine rows still carry deployment/inference blockers; #1174 being merged is not itself evidence that those blockers cleared.
- Correlated selections must be grouped into a single game-script cluster rather than presented as independent edges.
