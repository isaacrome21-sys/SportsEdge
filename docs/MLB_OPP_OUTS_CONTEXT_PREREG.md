# MLB context lane 2a: opponent profile → pitcher outs — pre-registration (v1, 2026-10-04)

Tracking: #1482 (backlog item D2a). Written and committed **before** any result was
seen. The research runner prints the SHA-256 of this file so the result comment is
bound to this exact protocol.

## Problem
Pitcher outs props are priced from the starter's own last 10 starts only
(`pitcher_joint_engine`, Jeffreys posterior with n = k). Lane 1 (#1509/#1513) showed
the opponent's strikeout profile moves pitcher K. Outs depend on pitch efficiency and
on how often the pitcher gets into trouble, both of which plausibly depend on the
opponent, but the sign is not obvious: high-strikeout lineups run up pitch counts
(fewer outs) yet also make weaker contact (more outs). So the test is sign-free.

## Opponent indices (both strictly before the game date)
Both use the exact shrunk index construction of lane 1
(`docs/MLB_OPP_K_CONTEXT_PREREG.md`): `rel(T, d) = (PA_cur * z_cur + W * z_prev) /
(PA_cur + W)`, W = 1000 PA, z = team rate / league rate, z_prev = 1 if no Y-1 data.
- **K index** (`kidx`): event = batter strikeouts (identical to lane 1).
- **On-base index** (`obidx`): event = hits + walks + hit-by-pitch, per PA.

## Candidate adjustment
For an evaluated start against opponent `O*` on `d*`, each own history start `i`
(outs `X_i`, opponent `O_i`, date `d_i`) is rescaled:

`x_i = X_i * (rel(O*, d*) / rel(O_i, d_i)) ** beta`

`x_i` is split linearly between `floor(x_i)` and `floor(x_i) + 1` (mass preserved,
clipped to [0, 27]) and the engine's Jeffreys posterior is applied with the unchanged
n = k. `beta = 0` is **exactly** the current production outs price.

Grid: index in {kidx, obidx} × beta in {-1, -0.75, -0.5, -0.25, 0.25, 0.5, 0.75, 1},
plus the production baseline (beta = 0). 17 candidates in total.

## Data
MLB StatsAPI, regular season (`gameType=R`):
- pitching game logs, seasons 2023-2025, every pitcher with `gamesStarted > 0`
  (rows with `gamesStarted >= 1`; outs from `inningsPitched`, opponent from the split);
- team hitting game logs, seasons 2022-2025, all 30 teams (`strikeOuts`, `hits`,
  `baseOnBalls`, `hitByPitch`, `plateAppearances`).

## Evaluation units
Every regular-season start where the pitcher had **k >= 5** prior starts in the
production window (seasons Y-1 and Y, strictly before the date), last 10, exactly as
production. The k = 1..4 prior-fallback path is out of scope.
- Tuning season: **2024**. Select the single candidate (index, beta) with the lowest
  mean RPS(outs). Ties go to the baseline, then to the earlier candidate in the order
  above.
- Held-out season: **2025**. Evaluated once with the frozen candidate.

## Metrics
- Primary: ranked probability score of P(over) over half-integer outs lines 0.5..26.5.
- Secondary: binary log loss and 10-bin ECE at typical lines 14.5/15.5/16.5/17.5.
- Information only: held-out RPS for every candidate, and the selected-vs-baseline
  table split by tercile of the selected index.

## Ship rule (all must hold on 2025)
1. The selected candidate is not the baseline (beta != 0).
2. RPS(selected) − RPS(baseline) has a 95% pitcher-clustered bootstrap CI (2000 reps,
   seed 20261004) entirely below 0.
3. Typical-line ECE(selected) <= ECE(baseline) + 0.005.

If any rule fails, the lane does not ship and pitcher outs stay own-history only.
If it ships, it changes only PITCHER_OUTS model_p on the k >= 5 path, half lines.
Pitcher props stay lean-tier; this does not promote any market (backlog item E).

## Production wiring (only if it ships)
A separate PR reuses the lane-1 opponent index fetch (adding the on-base fields if
`obidx` is selected), passes the rescaled outs to `pitcher_joint_engine` as weighted
rows (same n), shows `OPP-OUTS ADJ x<factor>` on the card, and includes a test
proving its prices equal this research code. If an input is missing, the row keeps
the unadjusted price and says so.

## How it runs
Open an `[MLB LINES]` issue whose fenced body is `RESEARCH opp_outs_context`. The
intake runs `scripts/research_mlb_opp_outs_context.py` in Actions and posts the report
on that issue. No lines are read and no card is produced.
