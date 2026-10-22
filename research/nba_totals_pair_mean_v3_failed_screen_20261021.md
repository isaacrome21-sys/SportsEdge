# NBA totals pair-mean V3 — frozen negative research result

**Verdict: `EXPLORATORY_NOT_BETTER_THAN_V2`. Do not activate, tune on this
cohort, promote, score as validated, or generate RUN IT card rows with V3.**

The exact 0.5 weight, 450 earlier-date games, minimum samples, shrinkage,
bootstrap settings and stop rules were committed before running the source in
`research/nba_totals_pair_mean_v3_prereg_20261021.md` (commit
`fc90c487f9121aea81ec70f3835f2a26e0d12471`). One historical evaluation
was run, with no post-result parameter changes.

## Pinned source and provenance

- Public upstream: `flancast90/sportsbookreview-scraper`, commit
  `1a820e50c6fbd0276cde073c22bfffae78930868`, path
  `data/nba_archive_10Y.json`, Git blob SHA-1
  `f5ba0d4f8f729236fdd8883a65189f2d6443338c`.
- Source raw 13,903 rows, normalized 13,893 games; identical V2 cohort,
  8,215 paired games across 2015–2021. No subsets were selected for verdict.
- Full machine-readable screen is
  `research/nba_totals_pair_mean_v3_failed_screen_20261021.json`;
  SHA-256 of the deterministic file output:
  `b0dbb53429fd0b6e466542a3e63d6b80100d2adbf27a15d874222ecbb4609cc4`.
- The runner proves V2 full cohort and arithmetic parity or refuses to emit
  results. Six focused standard-library regression tests passed.

## One-shot results (RMSE, points; lower is better)

| Forecast | 8,215 paired games |
|---|---:|
| V3 pair-mean challenger, weight 0.5 | **19.3001** |
| Parent V2 | 18.9770 |
| Rolling league mean | 20.0097 |
| Indicative SBR market reference | 18.0512 |

Mean squared-error disadvantage: V3 minus V2 **+12.3680**, with
calendar-day-cluster 750-draw seed-17 bootstrap percentile 95% interval
**[+10.0127, +14.4841]**. V3 minus indicative reference **+46.6476**,
interval **[+41.2585, +51.9776]**. This candidate under-predicted the
reference on 4,207 rows and over-predicted on 4,008 rows: its direction
counts are closer to balanced, but its scoring accuracy is materially worse.

| Season | V3 | V2 | Indicative reference |
|---|---:|---:|---:|
| 2015 | 18.5703 | 18.2996 | 17.5462 |
| 2016 | 18.6629 | 18.1283 | 17.2425 |
| 2017 | 19.0317 | 18.7031 | 17.9697 |
| 2018 | 19.8633 | 19.4502 | 18.4408 |
| 2019 | 20.0142 | 19.8150 | 19.0162 |
| 2020 | 19.4417 | 19.1278 | 18.2785 |
| 2021 | 19.5654 | 19.3661 | 17.9384 |

The archive is **calendar-date only**. Exact game tipoffs, when results
became available, quote capture timestamps, and exact bookmaker identity
are unknown. The indicative price is **not an authenticated close** and
the screen cannot produce verified betting edge, CLV, PLAY, or promotion
authority. These are retrospective diagnostics, not proof of a future edge.

## Engineering status / next evidence needed

- V3 is an isolated research artifact, not wired into pricing or card paths.
- V2's strict result-availability, identity and source guards are reused for
  real-timestamped inputs; the historical runner is separately labeled
  `STRICT_EARLIER_CALENDAR_DATES_ONLY` and never pretends to have true PIT.
- The active failed NBA game-total family stays diagnostic WATCH with no
  0–100 score, pending independent verification of score withholding.
- A future challenger requires **a newly preregistered design on an untouched
  evaluation cohort with admitted independent historical lines, timestamps
  and baselines**. Do not recycle this same cohort to tune weights.
