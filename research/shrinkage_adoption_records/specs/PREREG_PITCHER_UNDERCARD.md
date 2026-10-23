# PREREGISTRATION — MLB Pitcher Undercard Challenger (Model Fix Lane, family 2)

- **Directive and owner constraints:** as PREREG_BATTER_PROPS
  header (Isaac, Oct 14 2026: failed models get fixed as
  preregistered CHALLENGERS; production stays FROZEN; M2/M4
  verdicts precede any adoption; candidacy requires beating the
  frozen engine AND both naive baselines, paired CIs entirely
  < 0).
- **Label of any output:** RESEARCH_EVIDENCE — retrospective
  calibration evaluation. NOT a market verdict, NOT validation.
- **Written:** 2026-10-14, before any challenger score was
  computed on the test split declared in §4.
- **Families:** Pitcher Outs Recorded, Hits Allowed, Walks
  Allowed, Earned Runs. (Strikeouts excluded — its own frozen
  forward protocol; Pitches excluded — separate matrix row.)

## 1. The measured defect this challenger answers

Phase 2 (SPEC_PITCHER_UNDERCARD; n = 5,371 starts, 2024–2025):
the production joint engine (canonical phone-path configuration,
history pool only) is significantly worse than BOTH baselines on
all four markets — ΔCRPS vs B1 (pitcher's own raw trailing
distribution, uncapped) and vs B2 (league pool) all eight pooled
CIs entirely above zero, in both seasons. Outs: engine 2.1131,
B1 2.0920, B2 2.0540. The engine's empirical-Bayes machinery over
its ≤12-start pool loses to the raw pool itself, and the league
distribution beats everything — the signal in a short starter
window is real but small next to its variance. The challenger is
therefore the raw pool distribution explicitly shrunk toward the
league distribution.

## 2. Frozen evaluand (exact)

- Engine: `sportsedge/pitcher_joint_engine.py`
  `price_pitcher_market` (ENGINE_VERSION
  `mlb_pitcher_joint_empirical_bayes_v4_long_window_prior`) at
  origin/main `2a713380c` (byte-identical to the Phase 2 evaluand
  at `12999fc22`), canonical phone-path configuration:
  features = `{"history_pool": [...]}` only.
- Pool contract: `MLBPitcherPublicSource.prior_starts` semantics —
  same-season pitching gameLog, gamesStarted == 1 splits only,
  strictly prior dates, most recent ≤ 12 starts, ≥ 5 required or
  the fixture is excluded and counted.
- The frozen arm's implied CDF is reconstructed by the Phase 2
  sweep (§2(a) of SPEC_PITCHER_UNDERCARD: OVER probabilities over
  the predeclared grids OUTS 0.5–26.5, HITS_ALLOWED 0.5–14.5,
  BB 0.5–9.5, ER 0.5–11.5; monotonicity asserted).

## 3. Challenger construction (every constant fixed here)

For fixture start (pitcher p, date d) and market m:

- Base pool = ALL of p's prior same-season starts (gamesStarted
  == 1, strictly prior dates; NO 12-start cap — B1's pool), n
  starts, realized market values per start.
- League distribution L_m(d) = pooled empirical distribution over
  all starters' prior starts in the season to date — identical
  construction to Phase 2's B2.
- **Predictive PMF: P(v) = ( count_pool(v) + K · L_m(d)(v) ) /
  (n + K), with K = 10 starts-equivalent** (predeclared: twice the
  minimum eligible pool; at typical pool sizes this gives the
  pitcher's own history weight n/(n+10) ≈ 0.35–0.55 — the
  shrinkage direction and rough magnitude the Phase 2 deficits
  imply; never adjusted after test-split contact).
- CRPS computed under the identical support/truncation convention
  the Phase 2 evaluator applied to B1/B2 (the implementing code
  is reused or mirrored exactly, and the convention is restated
  in the results file).

## 4. Split discipline (declared before any run)

- **Design/diagnosis data:** 2024–2025 (Phase 2). **Test data:**
  the **2026 regular season** — untouched by Phase 2. This
  family's case is **SINGLE_SPLIT (2026)**.
- Population transposes Phase 2 §4 to 2026: regular-season starts
  where the §2 pool contract is satisfiable; exclusions counted
  (POOL_STARTS_LT_5). Sealed window: not applicable to 2026
  (declared).
- Acquisition (transport only, before scoring): StatsAPI
  players?season=2026 and pitching gameLogs 2026 into the program
  disk cache. Fallback if acquisition fails: FORWARD_ONLY filing,
  as in PREREG_BATTER_PROPS §4.

## 5. Arms scored (identical fixture set)

1. **FROZEN** — production engine, swept CDF (§2).
2. **CHALLENGER** — §3.
3. **B1** — pitcher's own trailing raw empirical distribution
   (uncapped) — Phase 2's definition; note the challenger's base
   pool equals B1's pool, so CHALLENGER vs B1 isolates the league
   shrinkage alone.
4. **B2** — league climatology.

## 6. Metrics and gate

- **Primary: CRPS** per market. **Secondary (descriptive):**
  Brier at the Phase 2 predeclared DK-typical lines (OUTS
  {14.5, 15.5, 16.5, 17.5, 18.5}; HITS_ALLOWED {4.5, 5.5, 6.5};
  BB {1.5, 2.5}; ER {1.5, 2.5}).
- Paired per-fixture ΔCRPS with 95% percentile CIs, block
  bootstrap over ISO calendar weeks, 2,000 resamples, **seed
  20261015**.
- **Adoption gate, per market:** ADOPT-CANDIDATE iff the
  challenger's ΔCRPS CI is entirely < 0 against FROZEN **and**
  B1 **and** B2. Otherwise KEEP FROZEN for that market. Markets
  verdicted separately.

## 7. Verification required before scoring

- **Parity:** ≥ 25 sampled (pitcher, fixture-date) pairs:
  evaluator pool == production `MLBPitcherPublicSource.prior_starts`
  pool with a cache-backed getter (25/25), mirroring Phase 2 §6
  (including its probable-pitcher sampling rule).
- **Sweep sanity:** ≥ 10 fixtures: engine `model_p` direct vs
  swept CDF at the market's median typical line, agreement
  < 1e-12 (Phase 2 §6).
- **Challenger unit checks:** PMF sums to 1 (1e-12); K → 0
  reduction to B1's distribution verified on samples (not scored).
- **Determinism:** fixed seed; re-runs reproduce results except
  timestamps.

## 8. What the verdict does and does not do

As PREREG_BATTER_PROPS §8: ADOPT-CANDIDATE is a recommendation to
Isaac only; adoption is a separate owner act sequenced after the
M2/M4 market verdicts. No re-tuning of K on the 2026 split is
permitted; a second challenger needs a new preregistration and a
new untouched split.
