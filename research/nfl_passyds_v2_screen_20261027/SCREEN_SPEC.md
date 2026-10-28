# NFL passing-yards v2 forward screen — scorer spec (RESEARCH_ONLY)

Status: implements the forward screen from the **draft** preregistration
`research/grok_nfl_passyds_v2_20261022/PREREG_DRAFT_NFL_PASSING_YARDS_V2.md`
(branch `grok/nfl-passyds-v2-prereg-focus-20261022` @ `7d6431ff816c`).
The draft is **not frozen**. This scorer freezes nothing, starts no clock,
and changes no PLAY eligibility. A PASS earns only a separate owner freeze
ruling; a completed window that fails is recorded `FAILED_SCREEN`.

## Construction F (fixed in the draft)

- `mu_v2 = mu_v1 * r`
- `r = (sum_y + K * mbar) / (sum_mu_v1 + K * mbar)`, `K = 200`
- Sums run over all PASS_YDS-qualified rows (frozen v1 gate) in weeks 4+ of
  the current season, in weeks **strictly before** the game; `mbar` is the
  mean `mu_v1` of those rows; no rows yet -> `r = 1`.
- `r` is recomputed per game week from in-season data only. There is no
  single global multiplier, and no prior-season correction is used (the
  draft's historical screen showed prior-season corrections overcorrect).
- Everything else is v1 exactly: PASS_YDS gate (QB, >= 3 prior games, mean
  prior attempts >= 20), `mu_for` with K = 3 shrinkage toward the league
  pool, and gamma CRPS with the frozen `cv = 0.3496`. v1 is imported from
  the pinned frozen evaluator
  (`research/nfl_props_part2_20261018/eval_nfl_props_calibration_v1.py`,
  sha256 `66de56155e3c36f90c1f39c648b24e724328ec86056dee0e9adbed57281bc25b`,
  the same pin the Part 2 pricer uses) after a hash check. v1 files and
  v1 scoring are never modified.

## Input contract

A data directory holding nflverse weekly player files in the frozen v1
layout — `ps_<season>.csv.gz` / `sp_<season>.csv.gz`, regular season rows
with `player_id`, `position`, `attempts`, `passing_yards` (the exact files
the v1 evaluator's `load()` consumes; the historical snapshot is pinned in
`research/nfl_props_part2_20261018/SPEC_HASHES.txt`). The screen reads the
2026 files from the same directory as they are published; their sha256 is
recorded in the output for provenance (forward files carry no pin). There
are no separate v1 projection files for this screen: the draft defines the
population on nflverse outcomes, and v1 mus are the frozen estimator's own
outputs, recomputed by the pinned evaluator. The Part 2 priced-run records
(the CLV clock) are a different artifact and are not this screen's input.

## Screen rule (draft section 4)

- Population: 2026 regular season, weeks 8+. Scoring stops after 4 full
  weeks: weeks 8-11 are scored; week 12+ rows are reported out-of-window
  and never scored.
- No verdict until all 4 window weeks are present (`SCREEN_INCOMPLETE`).
- `PASS_SCREEN` requires ALL of: mean dCRPS (v2 - v1) < 0; the 95%
  season-week-clustered CI upper bound < 0 (the evaluator's cluster
  bootstrap over season-week blocks, 2000 resamples); and
  |bias_v2| < |bias_v1| with bias = mean(mu - y) over scored rows.
- Otherwise, once the window is complete: `FAILED_SCREEN`.
