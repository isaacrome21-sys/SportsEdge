# MLB starter component vs defense blend (held-out only)

## Status
Research only. Not promotion evidence until a held-out window beats the incumbent defense blend.

## Incumbent
Production run means use the defense blend (recent team runs-for / runs-against).
See `scripts/validate_mlb_context_adjusted_history.py` and `sportsedge/mlb_context_adjusted_research.py`.

## Gate (same rule as prior failed starter attempt)
Promote a starter component **only if** on a held-out window it beats defense blend on:
1. Mean absolute calibration of full-game totals (lines 6.5 / 7.5 / 8.5 / 9.5), and
2. Mean Brier on those lines,
using the **shipped** Stage-1 distribution (Gamma-Poisson `r = 5.217229403204152` from #1238).

Do not retune dispersion inside this research track.

## Data caution
Schedule probable-pitcher fields are not proven pregame PIT. Any starter profile built from StatsAPI history is diagnostic unless bound to archived pregame starter identity.

## Next executable steps
1. Freeze tune / validate dates (prefer post-#1238 engine; exclude playoffs until separate window).
2. Emit side-by-side `defense_blend` vs `starter_adjusted` mean vectors per game.
3. Score both through `simulate_game_distribution(..., full_game_dispersion_r=DEFAULT_FULL_GAME_DISPERSION_R)`.
4. Publish numbers; open promotion PR only on a clear win.
