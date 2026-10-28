# DESIGN SCREEN REPORT — NFL team totals + period lines (activation pack)

**Run:** Oct 28, 2026 (script `screen_nfl_activation_v1.py`, output
`screen_results_v1.json`, generated 2026-10-28T04:26:26Z).
**Status: DESIGN SCREEN — an entry ticket, never validation.** Every
season screened is DESIGN data (seen by retired constructions). No
market verdict is issued or implied by anything here; the only market
numbers shown are the nflverse closing snapshot's implied team totals,
an untimestamped design diagnostic (gap G7), labeled as such wherever
they appear.

**Screen pass criteria — fixed in the script header before the run:**
team totals pass iff pooled candidate MAE < B1 and < B2 AND pooled CRPS
< B1 and < B2 AND no test season's candidate MAE is worse than its B2
MAE by more than 0.25. Periods pass iff pooled candidate MAE < B0 and
< B1 AND the candidate beats B0 in at least 4 of 6 buckets. The results
below are reported against those criteria as computed; nothing was
re-run with altered terms.

## Inputs (free, public; rolling release assets — hash of the pull used)

| Input | sha256 | Note |
|---|---|---|
| nflverse schedules `games.csv.gz` | `1b4ca0c70eea4236bf35eda85a04746ce031cafbafa962dfc7cc9572166535ec` | 7,548 rows. **Drift note:** draft PR #2831 pinned this asset at `82b05d70…` (515,925 bytes) hours earlier; this pull is 515,931 bytes with the same row count — the asset is updated in place upstream. This screen's provenance is the hash above, not the #2831 pin. |
| nflverse PBP 2023 | `bd3484731408def6b0ec93225bba2bd7b2c65769ca707a2b9444d891abdc6776` | period panel |
| nflverse PBP 2024 | `3fd2896bc0b911b615142d2f1fabae54a4bbba5ab7b73b28187b118ef8af6a3b` | period panel |
| nflverse PBP 2025 | `c6ecedd6d678cc37ed316b23ef84ee1ec6abb69c514bb11868a7ebd5a367df29` | period panel |

**Spread-sign proof (the sibling backtest's caught bug, re-proven
here):** correlation between `spread_line` and realized home margin
over 2020–2025 is +0.455, so the implied split uses
implied home = (total + spread)/2, away = (total − spread)/2, with the
sign taken from the data, never assumed.

**Period-panel integrity:** quarter points derive from play-by-play
running scores (quarter-end state = max cumulative score within the
quarter; the literal last row of a quarter is often a marker row with
null score-post fields). Validated against finals: 97.0% of 1,632
team-games match the final score exactly; 3.0% differ only by overtime
scoring (the panel is regulation quarters, by construction); zero
negative differences; zero NaNs.

## Team totals — `NFL_TEAM_TOTAL_DIST_V1`: SCREEN PASS (vs naive baselines)

Pooled CV from the 2018–2019 training seasons: c = 0.4644.
Pooled 2020–2025, n = 3,230 team-games:

| Metric | Candidate | B1 team mean | B2 league mean | Implied split (design diagnostic) |
|---|---|---|---|---|
| MAE | **7.749** | 7.831 | 7.924 | 7.250 |
| CRPS | **5.528** | 5.590 | 5.625 | — |

Calibration: PIT mean 0.537; 91.0% of realized scores inside the
central 90% interval.

Per season (MAE candidate / B1 / B2 / implied; CRPS candidate / B1 / B2):

| Season | n | MAE | CRPS |
|---|---|---|---|
| 2020 | 512 | 7.838 / 7.891 / 7.932 / 7.284 | 5.637 / 5.710 / 5.663 |
| 2021 | 544 | 8.205 / 8.211 / 8.438 / 7.663 | 5.826 / 5.833 / 5.904 |
| 2022 | 542 | 7.253 / 7.427 / 7.434 / 6.915 | 5.183 / 5.268 / 5.283 |
| 2023 | 544 | 7.749 / 7.825 / 7.918 / 7.318 | 5.537 / 5.606 / 5.624 |
| 2024 | 544 | 7.787 / 7.767 / 7.864 / 7.075 | 5.490 / 5.507 / 5.583 |
| 2025 | 544 | 7.667 / 7.865 / 7.954 / 7.247 | 5.500 / 5.622 / 5.691 |

**Disclosure, in the open (the NBA team-totals §0 pattern):** the
candidate beats the naive baselines it was screened against — narrowly
(≈0.08 MAE pooled) — and **loses clearly to the market's implied split**
(7.749 vs 7.250). The forward test's governing leg is accuracy against
the DraftKings closing team-total line, and on this design evidence
that leg is the expected-risk leg: the DK team-total line is not a
naive (total ∓ spread)/2 split of a stale total — it is a traded line
informed by the closing spread and total, which are themselves sharp.
The construction advances to ARMED-pending-freeze because the screen it
was given asked about the naive baselines and it passed, and because
the forward test — not this screen — is where the market question is
answered, with the moved-row and CLV legs measuring something MAE
against a snapshot cannot. Anyone reading this pass as market evidence
is misreading it.

## Period lines — `NFL_PERIOD_SHARE_V1`: FAILED_SCREEN

2023–2025, n = 1,632 team-games. MAE by bucket (candidate / B0 league
shares / B1 flat split):

| Bucket | Candidate | B0 | B1 |
|---|---|---|---|
| Q1 | 3.517 | 3.519 | 3.672 |
| Q2 | 4.261 | 4.246 | 4.279 |
| Q3 | 3.635 | 3.636 | 3.727 |
| Q4 | 4.314 | 4.257 | 4.269 |
| 1H | 5.450 | 5.439 | 5.423 |
| 2H (regulation) | 5.489 | 5.439 | 5.446 |
| **Pooled** | **4.444** | **4.423** | **4.469** |

The candidate beats the flat split but **does not beat league shares**
(pooled 4.444 vs 4.423; only Q1 and Q3 of six buckets beat B0). At an
~8-game sample, a team's own period shares are noise-dominated, and Q4
scoring is driven by game state (leading teams bleed clock; trailing
teams hurry), which a share profile cannot see. **Verdict:
FAILED_SCREEN for `NFL_PERIOD_SHARE_V1` as specified.** It is recorded,
not tuned away: no re-run with different shrinkage, sample caps, or
bucket definitions was performed or will be attached to this
construction. The family stays DESIGN ONLY; the design doc names the
successor direction (drive-level, game-state-conditioned period
scoring — a new construction) and the capture work that any period
construction needs regardless.

*Screens executed once, as committed. Reproduction: run
`screen_nfl_activation_v1.py` (pyarrow required for the PBP panel);
inputs are re-pulled from the nflverse releases and hash-recorded in
the output, so a later pull may show different hashes — the rolling
assets drift, and the drift is itself reported above.*

**Post-run note (disclosed, Oct 28, 2026):** after the run, the repo
lint gate flagged an undefined name in the script's league-mean
fallback branch (a list comprehension in `league_mean()`, reached
only when the prior season is entirely absent from history). That
branch never executed in this run — it would have raised immediately
— so no recorded number is affected; the one-token fix is in the
committed script, whose hash therefore differs from the byte state
that ran. The results file is the run's own output, unmodified.
