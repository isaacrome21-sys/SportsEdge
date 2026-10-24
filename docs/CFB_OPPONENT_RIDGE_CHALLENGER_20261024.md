# CFB opponent-adjusted research model — October 24, 2026

**SCREEN / NOT_VALIDATED.** This is a new challenger, not a replacement for the live model. No PLAY, stake, official, validated Model_P, capture-window or promotion authority. The reviewed t272 CFB calibration branch and frozen evaluators are untouched.

## Why a different model

The last-five raw-margin model can treat +20 against a weak opponent the same as +20 against a strong one. This challenger fits attack and defense against **the actual opponents played**. Every prior game supplies two equations: home points = league base + HFA/2 + home attack - away defense; away points = league base - HFA/2 + away attack - home defense. It uses weighted ridge to stabilize teams with few games and reduces previous-season weights to account for roster turnover. Home-field benefit is 4.31 points (research benchmark from t272); neutral sites get zero HFA. The resulting scoring model generates **separate home margin and total** estimates. The variance references (margin 16.46, total 16.34) are research assumptions from t272, not approved current-season calibration.

**No new 2025 Brier or closing-line advantage is claimed.** The t272 screen reported 2025 Brier ~0.273 spread and ~0.258 total on a separate cohort; this challenger must beat that baseline on **identical games and reference semantics** before anyone describes it as an improvement.

## The supplied handicap checklist

The source-audit interface supports source/date/value fields for:

- **Core:** offensive/defensive efficiency, EPA/play, success rate, yards/play, explosive plays, havoc, offensive/defensive fronts, secondary, QB, skill players, talent/depth, scheme, recent form.
- **Situational:** verified neutral venue, home advantage, rest/travel, injuries and availability, weather, motivation, coaching, red zone, third down, turnovers, special teams, field position.
- **Market/context:** opening/current line, market movement, public splits, consensus, officiating (low weight unless shown to add signal).

**Important distinction:** only actual observed scores against opponents currently affect the model's point projections. The other factors are accepted as *documented pregame claims only* when they include an HTTPS source and a timestamp earlier than the prediction. Those source strings are not cryptographically authenticated by this code. Advanced factor coefficients are deliberately **zero** until independent historical pregame data can be fitted and tested. In particular, a self-labeled official QB source is not an automatically confirmed starter. Market context is comparison-only and never enters a supposedly market-independent prediction. Illinois college exclusions and established Form2 QB identity controls stay with the original run gate.

## Walk-forward evaluation

Use an input JSON **list** of timestamped completed games, with fields:
\`game_id\`, integer \`season\`, \`home\`, \`away\`, \`kickoff_utc\`,
\`result_observed_at_utc\`, \`home_points\`, \`away_points\`, boolean
\`neutral_site\`; target-year games optionally carry
\`reference_spread_home\` and \`reference_total\`.

\`\`\`bash
python scripts/eval_cfb_opponent_ridge_challenger.py \
  --games /path/to/chronological_game_rows.json --season 2025 \
  --out artifacts/cfb/opponent_ridge_screen_2025.json
\`\`\`

For each target game the fit includes **only previously completed and observed games** from that season and the immediately preceding season. The evaluator excludes pushes from Brier, reports model vs reference absolute errors, and emits explicit insufficient-history and no-reference results. It cannot produce historical line receipt times, executable sportsbook prices, CLV, actual EV, or promotion from a retrospective reference.

## What's still required

1. Source and timestamp the real 2024/2025 completed-game corpus and join it to the exact same t272 631-game market-reference cohort; run the CLI and compare Brier, calibration and reference MAE honestly.
2. Collect *pregame* QB identity/availability, talent-depth, EPA/success/explosive/havoc, pace, line, injuries and weather. Fit each incremental factor only in chronological training and test it on untouched later games. Do not use today's postgame boxscore features as if known pregame.
3. Keep prior markets separate; recheck real current DK quotes, no-vig and -165 cap at release. No validation or bet status may change without independently reviewed evidence.
