# MLB context lane 1: opponent strikeout rate → pitcher K — pre-registration (v1, 2026-10-04)

Tracking: #1482 (backlog item D). Written and committed **before** any result was
seen. The research runner prints the SHA-256 of this file so the result comment is
bound to this exact protocol.

## Problem
Context (lineups, umpire, Statcast, weather) is retrieved for the card but never
enters model_p. Pitcher strikeout props are priced from the starter's own last 10
starts only (`pitcher_joint_engine`, Jeffreys posterior with n = k), so a start
against a high-strikeout lineup is priced the same as one against a contact lineup,
and a pitcher whose recent starts came against weak/strong lineups is not de-biased.

This is the first context lane. It uses the **opposing team's** strikeout rate
(available pregame from StatsAPI team stats). A batter-level lineup version and an
umpire lane are later, separate pre-registrations.

## Opponent strikeout index
For team `T` on date `d` in season `Y` (all inputs strictly before `d`):
- `z_prev(T)` = T's season Y-1 batting K/PA divided by the Y-1 league K/PA.
- `z_cur(T, d)` = T's season-Y K/PA over games dated before `d`, divided by the
  league K/PA over all team games dated before `d` in season Y.
- `rel(T, d) = (PA_cur * z_cur + W * z_prev) / (PA_cur + W)` with **W = 1000 PA**.
  If T has no season-Y PA yet, `rel = z_prev`. If T has no Y-1 data, `z_prev = 1`.

## Candidate adjustment
For an evaluated start against opponent `O*` on date `d*`, each of the pitcher's own
history starts `i` (strikeouts `K_i`, opponent `O_i`, date `d_i`) is rescaled:

`x_i = K_i * (rel(O*, d*) / rel(O_i, d_i)) ** beta`

`x_i` is split linearly between `floor(x_i)` and `floor(x_i) + 1` (mass preserved,
values clipped at 20) and the engine's Jeffreys posterior is applied with the
unchanged n = k. `beta = 0` is **exactly** the current production K price.

Grid: `beta` in {0, 0.25, 0.5, 0.75, 1.0, 1.25}.

## Data
MLB StatsAPI, regular season (`gameType=R`):
- pitching game logs, seasons 2023-2025, every pitcher with `gamesStarted > 0`
  (rows with `gamesStarted >= 1` are starts; the split's `opponent.id` is `O_i`);
- team hitting game logs (`teams/{id}/stats?stats=gameLog&group=hitting`), seasons
  2022-2025, all 30 teams (`strikeOuts`, `plateAppearances`).

## Evaluation units
Every regular-season start where the pitcher had **k >= 5** prior starts in the
production window (seasons Y-1 and Y, strictly before the game date), using the last
10, exactly as production. (The k = 1..4 fallback path is out of scope.)
- Tuning season: **2024**. Select the beta that minimizes mean RPS(K).
- Held-out season: **2025**. Evaluated once with the frozen beta.

## Metrics
- Primary: ranked probability score of P(over) over half-integer K lines 0.5..19.5.
- Secondary: binary log loss and 10-bin ECE at typical lines 3.5/4.5/5.5/6.5.
- Information only: the same table split by opponent-index tercile.

## Ship rule (all must hold on 2025)
1. The tuned beta is > 0.
2. RPS(beta*) − RPS(beta = 0) has a 95% pitcher-clustered bootstrap CI (2000 reps,
   seed 20261004) entirely below 0.
3. Typical-line ECE(beta*) <= ECE(beta = 0) + 0.005.

If any rule fails, the lane does not ship and pitcher K stays own-history only.
If it ships, it changes only PITCHER_K model_p on the k >= 5 path. Pitcher props stay
lean-tier; this does not promote any market (that is backlog item E).

## Production wiring (only if it ships)
A separate PR fetches the opponent index pregame, passes the rescaled K values to
`pitcher_joint_engine` as weighted rows (same n), shows `OPP-K ADJ x<factor>` on the
card, and includes a test proving its prices equal this research code. If the
opponent index can't be fetched, the row falls back to the unadjusted price and says
so. Until then nothing in production changes.

## How it runs
Open an `[MLB LINES]` issue whose fenced body is `RESEARCH opp_k_context`. The intake
script runs `scripts/research_mlb_opp_k_context.py` in Actions and posts the report
on that issue. No lines are read and no card is produced.
