# SportsEdge Football Foundation v0.1

Parallel NFL/CFB foundation modeled after the MLB production contract, without inheriting MLB-specific model assumptions.

## Core contract

- External validation registry is the sole authorization source.
- MODEL_STATUS and BET_STATUS remain separate.
- Every source is timestamped with authority, TTL, and SOURCE_CONFLICT handling.
- No post-kickoff data may enter a pregame feature vector.
- Market probability is a benchmark/challenger, never a substitute for Model_P.
- Preseason is a distinct NFL regime; regular-season parameters are not silently reused.
- CFB and NFL have separate calibration/feature registries and may not share weights unless out-of-sample evidence supports transfer.

## Initial market families

NFL: moneyline, spread, total, team total, 1H/1Q derivatives, player passing/rushing/receiving props, anytime TD, SGP only after joint-path validation.

CFB: moneyline, spread, total, team total, 1H derivatives, selected player props where reliable point-in-time depth-chart/role data exists.

## Football feature families

- Market baseline: opening/current no-vig probabilities and line movement, preserved by timestamp.
- Team efficiency: EPA/play, success rate, explosive-play rate, early-down pass rate, pressure/sack rates, red-zone efficiency.
- Personnel: QB, OL continuity, skill-player availability, defensive front/secondary availability, depth chart, suspensions.
- Situational: rest, travel, time zone, surface, altitude, weather, coaching changes.
- Preseason only: expected QB rotation, starter snap limits, backup depth, coach comments, roster-cut incentives, practice participation.
- CFB only: returning production, transfer/QB continuity, coordinator/scheme change, class/experience, FBS/FCS transition context.

## Research architecture

M0 = raw no-vig market.
M1 = leakage-safe calibrated market.
M2 = M1 + strongly regularized football residual features.

Primary research test is paired M2 vs M1 on chronological holdout data. Positive backtests do not authorize deployment until artifact/runtime parity and live-input gates pass.
