# MLB context lane 2b: home-plate umpire → pitcher K and BB — pre-registration (v1, 2026-10-04)

Tracking: #1482 (backlog item D2b). Written and committed **before** any result was
seen. The research runner prints the SHA-256 of this file so the result comment is
bound to this exact protocol.

## Problem
The card retrieves tonight's home-plate umpire (`sportsedge/mlb_umpire_source.py`) but
the umpire does not enter model_p. A plate umpire's zone plausibly moves strikeouts
and walks for both starters. Production prices today:
- **PITCHER_K** (k ≥ 5, half lines): own last ≤10 starts rescaled by the validated
  opponent-K index (lane 1, #1509/#1513, beta = 1), Jeffreys posterior with n = k.
- **PITCHER_BB** (k ≥ 5, half lines): own last ≤10 starts, Jeffreys posterior, n = k.

This study tests two separate sub-lanes, each with its own selection and ship rule:
**2b-K** (umpire K index → PITCHER_K) and **2b-BB** (umpire BB index → PITCHER_BB).

## Umpire index (strictly before the game date)
Game totals: for every regular-season game `g` with a known home-plate umpire `u(g)`,
`K_g`, `BB_g` and `PA_g` are the sums over **both** teams' hitting game logs for that
`gamePk` (`strikeOuts`, `baseOnBalls`, `plateAppearances`). Games missing either team's
row, or without a home-plate umpire in the schedule `officials` hydration, are not used.

For umpire `u`, stat `s` in {K, BB}, date `d` and shrinkage weight `W` (in PA):
- window = games with date in `[d − 365 days, d)` (same-day games excluded);
- `S_u`, `PA_u` = sums over `u`'s games in the window; `r_L` = league `S / PA` over
  all usable games in the window;
- `rel_s(u, d; W) = (S_u + W · r_L) / ((PA_u + W) · r_L)`.
- If `u` is unknown or has no games in the window, `rel = 1` (neutral).
  If the league window is empty, `rel = 1`.

## Candidate adjustment
For an evaluated start on `d*` with umpire `u*`, each own history start `i` (date `d_i`,
umpire `u_i`, raw count `X_i`) is rescaled:

- **2b-K:** `x_i = X_i · (opp*/opp_i)^1 · (rel_K(u*, d*) / rel_K(u_i, d_i))^beta`, where
  the first factor is the production lane-1 opponent-K adjustment, unchanged.
- **2b-BB:** `x_i = X_i · (rel_BB(u*, d*) / rel_BB(u_i, d_i))^beta`.

`x_i` is split linearly between `floor(x_i)` and `floor(x_i) + 1` (mass preserved;
clipped to [0, 20] for K and [0, 10] for BB) and the engine's Jeffreys posterior is
applied with the unchanged n = k. `beta = 0` is **exactly** the current production price
of each market (tested against `pitcher_joint_engine`).

Grid (each sub-lane): `W` in {2000, 6000} × `beta` in {0.5, 1, 1.5, 2}, plus the
production baseline. 9 candidates per sub-lane, in this order: baseline,
(2000, 0.5), (2000, 1), (2000, 1.5), (2000, 2), (6000, 0.5), …, (6000, 2).
Only positive betas are tested: an umpire whose games run more strikeouts (walks) is
expected to raise, not lower, both starters' counts. (An umpire typically works
~30 plate games, ~2,300 PA, per season, so W = 2000 shrinks a full season about halfway.)

## Data
MLB StatsAPI, regular season (`gameType=R`):
- schedule with `hydrate=officials`, seasons 2022–2025 (home-plate umpire per `gamePk`);
- team hitting game logs, seasons 2022–2025, all 30 teams (also feeds lane 1's index);
- pitching game logs, seasons 2023–2025, every pitcher with `gamesStarted > 0`
  (rows with `gamesStarted >= 1`; strikeouts, walks, opponent and `gamePk`).

## Evaluation units
Every regular-season start where the pitcher had **k ≥ 5** prior starts in the
production window (seasons Y-1 and Y, strictly before the date, last 10), exactly as
production, **and** tonight's home-plate umpire is known. History starts with an unknown
umpire take `rel = 1`. The k = 1..4 prior-fallback path is out of scope.
- Tuning season: **2024**. For each sub-lane, select the single candidate with the
  lowest mean RPS. Ties go to the baseline, then to the earlier candidate in the order above.
- Held-out season: **2025**. Each sub-lane is evaluated once with its frozen candidate.

## Metrics
- Primary: ranked probability score of P(over) over half-integer lines
  (K: 0.5..19.5; BB: 0.5..9.5).
- Secondary: binary log loss and 10-bin ECE at typical lines (K: 3.5/4.5/5.5/6.5;
  BB: 0.5/1.5/2.5/3.5).
- Information only: held-out RPS for every candidate, the selected-vs-baseline table by
  tercile of the target umpire index, the count of starts dropped for an unknown umpire,
  and the share of usable games.

## Ship rule (per sub-lane, all must hold on 2025)
1. The selected candidate is not the baseline (beta ≠ 0).
2. RPS(selected) − RPS(baseline) has a 95% pitcher-clustered bootstrap CI (2000 reps,
   seed 20261004) entirely below 0.
3. Typical-line ECE(selected) ≤ ECE(baseline) + 0.005.

A sub-lane that fails any rule does not ship, and that market keeps its current price.
2b-K and 2b-BB are decided independently. Shipping changes only PITCHER_K and/or
PITCHER_BB model_p on the k ≥ 5 path, half lines. Pitcher props stay lean-tier; this
does not promote any market (backlog item E).

## Production wiring (only if a sub-lane ships)
A separate PR builds the umpire index pregame from the schedule `officials` hydration for
the trailing 365 days plus the team logs the opponent index already fetches, passes the
rescaled counts to `pitcher_joint_engine` (same n), shows `UMP-K ADJ x<factor>` /
`UMP-BB ADJ x<factor>` on the card, and includes a test proving its prices equal this
research code. If the umpire is not yet assigned or any input is missing, the row keeps
its current price and the card says `UMP-… UNADJUSTED <why>`. This lane never blocks a row.

## How it runs
Open an `[MLB LINES]` issue whose fenced body is `RESEARCH umpire_context`. The intake runs
`scripts/research_mlb_umpire_context.py` in Actions and posts the report on that issue. No
lines are read and no card is produced.
