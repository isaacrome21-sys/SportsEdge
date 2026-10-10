# MLB context lanes: 2026 stability check — pre-registration (v1, 2026-10-10)

Tracking: #1482 (2027 prep). Written and committed **before** any 2026 regular-season
start was scored with these lanes in a research run. The runner prints the SHA-256 of
this file so the result comment is bound to it.

## Question
Three context lanes are live on the phone card (lean-tier, k ≥ 5, half lines). Each was
selected on 2024 and passed one held-out look on 2025:

| lane | market | frozen production config | baseline it adjusts | source |
|---|---|---|---|---|
| OPP-K | PITCHER_K | opponent K index, beta = 1.0 | own last-10 history | #1509 / #1513 |
| OPP-OUTS | PITCHER_OUTS | `obidx`, beta = −0.25 | own last-10 history | #1523 / #1524 |
| UMP-BB | PITCHER_BB | umpire BB index, W = 6000, beta = 2.0 | own last-10 history | #1528 / #1532 |

Do these frozen configs still help (or at least not hurt) on the **2026 regular
season**, which none of the selections or tests ever saw? The answer decides whether
each lane stays on for 2027.

## Prices tested (frozen, no tuning)
The research `predict_k`, `predict_outs` and `predict("bb", …)` functions, which are
parity-tested against the engine to 1e-12 (#1513, #1524, #1532), at exactly the frozen
production configs above, against their baselines (beta = 0 / own history only). The
indices are the same constructions as the original studies: opponent index from team
hitting game logs (strictly prior, W = 1000 PA shrinkage to Y−1); umpire index from
schedule `officials` plus both teams' game rows (trailing 365 days, strictly prior).

Not reproduced: the LINEUP-K lane (#1540; needs per-game lineups and boxscores) and
the presentation guards. Few-starts fallback rows (k = 1..4) are out of scope.

## Data and units
- StatsAPI, `gameType=R` only. Starters of seasons 2024, 2025, 2026 (pitching game
  logs); team hitting game logs for all 30 teams, 2023–2026; schedules hydrated with
  officials, 2023–2026 (March–October, monthly).
- One unit = one start with ≥ 5 prior starts in seasons Y−1..Y (the production k ≥ 5
  path, last 10 used). UMP-BB units also need a known home-plate umpire.
- **Held-out season: 2026.** 2025 is used only for the informational re-tune below.
- Fail closed: < 250 starters in a season, a team log with < 100 games, or < 90% of
  games with a home-plate umpire aborts the run (no result).

## Metric
Per lane: mean RPS over the lane's full threshold grid (as in the original study),
frozen config minus baseline, on 2026. 95% CI: pitcher-cluster bootstrap, 2000 reps,
seed 20261004 (the original studies' seed). Typical-line 10-bin ECE and log loss on
the original typical lines (K {3.5, 4.5, 5.5, 6.5}; outs {14.5, 15.5, 16.5, 17.5};
BB {0.5, 1.5, 2.5, 3.5}).

## Decision rule (per lane)
- **DISABLE for 2027** if either holds on 2026:
  1. the 95% CI of the RPS difference lies entirely above 0 (the frozen lane is
     significantly worse than its baseline), or
  2. typical-line ECE of the frozen lane > baseline ECE + 0.005.
- Otherwise **KEEP**, labelled **CONFIRMED** if the CI lies entirely below 0, or
  **KEEP (not confirmed)** if it covers 0.

DISABLE means a separate PR turns that lane off for games from 2027-01-01 (the card
prices the baseline and shows `… UNADJUSTED … disabled by 2026 stability check`).
That PR touches an engine-pinned file, so its ML v2 clock impact is checked first.
KEEP changes nothing.

## Information only (cannot change anything)
The original selection procedure re-run with tune 2025 → the candidate it would pick,
and that candidate's 2026 RPS. A different pick does **not** change the production
config; changing a beta would need its own pre-registration and a later held-out
season. Also reported: per-lane units, mean outcome 2025 vs 2026, index spread.

There is no re-run with other seasons, grids or windows.

## How it runs
Open an `[MLB LINES]` issue whose fenced body is `RESEARCH context_lane_stability_2026`.
The intake runs `scripts/research_mlb_context_lane_stability_2026.py` in Actions and
posts the report on that issue. No lines are read and no card is produced.
