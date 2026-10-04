# MLB context lane 2c: announced-lineup strikeout rate → pitcher K — pre-registration (v1, 2026-10-04)

Tracking: #1482 (backlog item D2c). Written and committed **before** any result was
seen. The research runner prints the SHA-256 of this file so the result comment is
bound to this exact protocol.

## Problem
PITCHER_K (k ≥ 5, half lines) is priced today from the starter's own last ≤10 starts,
each rescaled by the validated **team-level** opponent strikeout index (lane 1,
#1509/#1513, beta = 1), Jeffreys posterior with n = k. The team index describes the
opponent's season, not tonight's nine hitters: a rest day for two high-strikeout
regulars, or a platoon-heavy lineup, is invisible to it. The card already retrieves the
announced batting order (`sportsedge/mlb_game_context_source.py`), but it does not enter
model_p.

This lane tests whether tonight's **announced lineup** adds K signal **on top of** the
production team index. The 2b umpire K test (#1528) showed that a plausible context
signal can carry nothing extra once opp-K is in, so the baseline here is the current
production price, not own history.

## Batter and lineup index (strictly before the game date)
League rate: `r_L(d, Y)` = league K/PA from all 30 teams' hitting game logs over
season `Y-1` (full) plus season `Y` games dated before `d`.

Batter rate, for batter `b`, date `d`, season `Y` and shrinkage weight `W_b` (PA):
- `K_b`, `PA_b` = the batter's regular-season strikeouts and plate appearances over
  season `Y-1` (full) plus season `Y` games dated before `d` (same-day games excluded);
- `r_b = (K_b + W_b · r_L) / (PA_b + W_b)`. A batter with no prior PA gets `r_L`.

Lineup index for one team's batting order on date `d` (exactly 9 starters, slots 1–9):
- slot weights `w = (4.65, 4.55, 4.45, 4.35, 4.25, 4.15, 4.05, 3.95, 3.85)` (expected PA
  by batting-order slot, fixed here);
- `L = Σ_s w_s · r_b(s) / (r_L · Σ_s w_s)`.
- A batting order that does not have exactly 9 distinct batters is **unknown**.

Lineup deviation from the team index: `D = L / opp_rel(T, d)`, where `opp_rel` is the
production lane-1 opponent K index of that team on that date (unchanged, W = 1000 PA).

## Candidate adjustment
For an evaluated start on `d*` against announced lineup `*`, each own history start `i`
(date `d_i`, raw strikeouts `K_i`, opponent's batting order in that game) is rescaled:

`x_i = K_i · (opp*/opp_i)^1 · (D* / D_i)^gamma`

The first factor is the production lane-1 adjustment, unchanged. If history start `i`'s
opposing lineup is unknown, `D_i = 1`. `x_i` is split linearly between `floor(x_i)` and
`floor(x_i) + 1` (mass preserved; clipped to [0, 20]) and the engine's Jeffreys posterior
is applied with the unchanged n = k. `gamma = 0` is **exactly** the current production
PITCHER_K price (tested against `pitcher_joint_engine` with `opp_k_adjustment`).
`gamma = 1` means tonight's lineup fully replaces the team index on both sides.

Grid: `W_b` in {200, 600} × `gamma` in {0.25, 0.5, 0.75, 1.0}, plus the production
baseline. 9 candidates, in this order: baseline, (200, 0.25), (200, 0.5), (200, 0.75),
(200, 1), (600, 0.25), …, (600, 1). Only positive gamma is tested: a lineup that
strikes out more than its team's index should raise, not lower, the starter's K.

## Data
MLB StatsAPI, regular season (`gameType=R`):
- schedule, seasons 2022–2025 (final regular-season `gamePk`s and official dates);
- `game/{gamePk}/boxscore` for every such game: each side's team id, `battingOrder`,
  and every player's `stats.batting` `strikeOuts` and `plateAppearances` (batter rates);
- team hitting game logs, seasons 2022–2025, all 30 teams (league rate and lane-1 index);
- pitching game logs, seasons 2023–2025, every pitcher with `gamesStarted > 0`.

## Evaluation units
Every regular-season start where the pitcher had **k ≥ 5** prior starts in the production
window (seasons Y-1 and Y, strictly before the date, last 10), exactly as production,
**and** the opposing team's batting order for that game is known. (Production can only
apply this lane once the lineup is posted; before that the K row keeps its current price.)
The k = 1..4 prior-fallback path is out of scope.
- Tuning season: **2024**. Select the single candidate with the lowest mean RPS. Ties go
  to the baseline, then to the earlier candidate in the order above.
- Held-out season: **2025**. Evaluated once with the frozen candidate.

The runner refuses to score if fewer than 90% of final games have both batting orders.

## Metrics
- Primary: ranked probability score of P(over) over half-integer K lines 0.5..19.5.
- Secondary: binary log loss and 10-bin ECE at typical lines 3.5/4.5/5.5/6.5.
- Information only: held-out RPS for every candidate; the selected-vs-baseline table by
  tercile of the target `D*` (W_b = 200); the p10–p90 spread of `D*`; starts dropped for
  an unknown target lineup; history starts with an unknown lineup.

## Ship rule (all must hold on 2025)
1. The selected candidate is not the baseline (gamma ≠ 0).
2. RPS(selected) − RPS(baseline) has a 95% pitcher-clustered bootstrap CI (2000 reps,
   seed 20261004) entirely below 0.
3. Typical-line ECE(selected) ≤ ECE(baseline) + 0.005.

If any rule fails, the lane does not ship and PITCHER_K keeps its current price. If it
ships, it changes only PITCHER_K model_p on the k ≥ 5 path, half lines, and only when
tonight's lineup is posted. Pitcher props stay lean-tier; this does not promote any
market (backlog item E).

## Production wiring (only if it ships)
A separate PR builds the batter rates pregame (per-batter hitting game logs for seasons
Y-1 and Y, the same counts the boxscores sum to), the history lineups from the boxscores
of the starter's last ≤10 starts, and `r_L` from the 90 team logs lane 1 already
memoizes. It passes the rescaled K values to `pitcher_joint_engine` (same n), shows
`LINEUP-K ADJ x<factor>` on the card, and includes a test proving its prices equal this
research code. If the lineup is not posted or any input is missing, the row keeps the
lane-1 price and the card says `LINEUP-K UNADJUSTED <why>`. This lane never blocks a row.

## How it runs
Open an `[MLB LINES]` issue whose fenced body is `RESEARCH lineup_k_context`. The intake
runs `scripts/research_mlb_lineup_k_context.py` in Actions and posts the report on that
issue. No lines are read and no card is produced.
