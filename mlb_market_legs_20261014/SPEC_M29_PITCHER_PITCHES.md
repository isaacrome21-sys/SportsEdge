# SPEC — MLB Pitcher Pitches Thrown Calibration Backtest (M29)

Family: Pitcher Pitches Thrown (`PITCHER_PITCHES`). The family is
**unregistered** (issue #2264; a registration package is prepared and
awaits an owner decision). Registration is a governance act, not an
evaluation input: this evaluation measures the distribution the
engine already prices, and **changes no registration state**.

- **Label of any output:** RESEARCH_EVIDENCE — retrospective
  calibration evaluation. NOT a market verdict (no historical paired
  DK lines for this family; the market leg is
  FORWARD_ONLY_BY_DESIGN), NOT validation, NOT a promotion input.
- **Written:** 2026-10-15, before any pitches score was computed.
  Stage 2 of the MLB market-leg lane. This spec mirrors
  SPEC_PITCHER_UNDERCARD (Phase 2, item 2) wherever the construction
  is shared, and says so where it differs.

## 1. Model identity (exact)

- Engine: `sportsedge/pitcher_joint_engine.py`
  `price_pitcher_market` (ENGINE_VERSION
  `mlb_pitcher_joint_empirical_bayes_v4_long_window_prior`) at main
  `83e0c396a4761ea3de80583be5e61e8ca2e07f9a`. The file's blob at this
  pin is `00cba6f664e313b53ab0084e6f3f471a9d85b566` — **identical**
  to its blob at the Phase 2 pin `12999fc22`, so the engine scored
  here is byte-identical to the one the undercard evaluation scored.
- Configuration: the canonical phone-path configuration of the
  undercard spec §1 — features = `{"history_pool": [...]}` only.
  `PITCHER_PITCHES` is in the engine's `PRICED_PITCHER_MARKETS` and
  reads the pool rows' measured `pitches` field (parsed from
  StatsAPI `numberOfPitches` by the production collector); the
  engine fails closed on pools that lack it.
- Pool assembly: identical to the undercard spec §1
  (`MLBPitcherPublicSource.prior_starts` semantics — same-season
  pitching gameLog; gamesStarted == 1 splits only; strictly prior
  dates; most recent ≤ 12 starts; ≥ 5 required).

## 2. Declared evaluation configuration

- (a) **Distribution reconstruction.** As undercard §2(a): the
  engine's implied predictive CDF is reconstructed by sweeping
  `price_pitcher_market` (market PITCHER_PITCHES, side OVER) over
  half-lines m + 0.5 for integer m, F(m) = 1 − p_over(m + 0.5).
  Sweep range: m = 0..170. Monotonicity of the swept CDF is asserted
  per fixture; a violation stops the run.
- (b) **CRPS truncation.** CRPS = Σ_m (F(m) − 1{y ≤ m})² over
  m = 0..170, identical for engine, B1 and B2 (the undercard tail
  rule: the sum is truncated at the declared bound; the mean
  residual tail mass 1 − F(170) is reported — for pitch counts this
  bound sits far above any realized workload, and the tail mass is
  expected at ~0; it is reported, not assumed).
- (c) **Data transport and sealed window:** identical to the
  undercard spec §2(b) — the same StatsAPI disk cache
  (`~/workspace/tmp/bt_data/statsapi_cache`, identity in
  `DATASET_MANIFEST_STAGE2.md`); fixtures in [2024-07-01,
  2024-09-01) excluded from scoring and starts in the window removed
  from every pool before the ≤ 12 cap.

## 3. Point-in-time audit

Identical to the undercard spec §3, with the outcome = the pitcher's
realized measured pitch count in the fixture start, used only after
prediction. Market prices never enter (no market leg exists).

## 4. Population

- The undercard population: regular-season MLB starts, seasons
  **2024 and 2025**, where the production pool (§1) is satisfiable
  (≥ 5 prior same-season starts). The undercard run scored 5,371
  fixtures on this definition.
- Additional exclusions, counted per season (pitches-specific):
  - `PITCHES_NOT_MEASURED` — the fixture's own gameLog row carries
    no measured pitch count, so no outcome exists to score.
  - `POOL_PITCH_COUNT_MISSING` — the engine refuses the fixture's
    pool because a pool row lacks a measured pitch count (the
    engine's own fail-closed rule, §1).
- No other exclusions are permitted. The scored n and both exclusion
  counts are reported per season, reconciled against the undercard
  population.

## 5. Metrics and gate

- **Primary: CRPS** of the engine's implied pitches distribution
  (§2) vs the realized pitch count, on the identical fixture set.
- Baselines, scored identically (the undercard spec §5 pair):
  - **B1 — pitcher's own trailing raw frequency:** the empirical
    distribution of measured pitch counts over ALL of the pitcher's
    prior same-season starts (no 12-start cap, no posterior).
  - **B2 — league climatology:** pooled empirical distribution of
    measured pitch counts over all starters' prior starts in the
    season to date (strictly prior dates, sealed-window starts
    removed).
- Paired per-fixture differences (engine − baseline) with 95%
  percentile CIs, block bootstrap over ISO calendar weeks, 2,000
  resamples, seed 20261015. Per-season and pooled reporting.
- **Gate (declared before results):** BEATS_BASELINE iff the pooled
  paired ΔCRPS CI is entirely < 0 against BOTH baselines. Otherwise
  DOES_NOT_BEAT_BASELINE, CI positions reported.
- Descriptive (not gated): mean predicted vs mean realized pitch
  counts; empirical coverage of the distribution's central 80%
  interval (p10–p90 from the swept CDF); mean residual tail mass
  (§2b). No per-line Brier table is declared for this family: DK
  hangs pitches at starter-specific lines, no canonical line set
  exists, and inventing one after seeing the data would be exactly
  the post-hoc freedom this program refuses — stated here, before
  results, as the reason.

## 6. Verification required before scoring

- **Parity:** ≥ 25 sampled (pitcher, fixture-date) pairs: the
  evaluator's pool must equal the production
  `MLBPitcherPublicSource.prior_starts` pool (the undercard §6
  construction and restrictions). 25/25 pool equality required —
  the undercard run's parity artifact may be re-verified rather
  than re-run only if the evaluator's pool code is byte-identical
  to the undercard evaluator's; otherwise parity runs fresh.
- **Sweep sanity:** for ≥ 10 fixtures, engine `model_p` at a
  mid-range line computed directly equals the swept CDF's implied
  value at that line to < 1e-12.
- **Determinism:** fixed seed; re-runs reproduce results except
  timestamps.

## 7. What verdicts do and do not unlock

Calibration evidence only. The market leg stays forward-only; the
family's registration question (#2264) is untouched by any outcome
here — a pass does not register the family and a fail does not
deregister the engine's ability to price it in research. Reported
in full either way.
