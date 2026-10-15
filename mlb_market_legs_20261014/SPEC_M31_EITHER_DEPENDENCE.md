# SPEC — EITHER_PITCHER Dependence Audit, HA / BB / ER (M31)

Families: `EITHER_PITCHER_HITS_ALLOWED`, `EITHER_PITCHER_BB`,
`EITHER_PITCHER_ER`. (`EITHER_PITCHER_K` does not exist anywhere in
the engine, catalog, or settlement layers and is out of scope.)

- **Label of any output:** RESEARCH_EVIDENCE — retrospective
  measurement of a construction's calibration error. NOT a market
  verdict, NOT validation, NOT a promotion input. The family stays
  behind `EITHER_PITCHER_DEPENDENCE_UNMEASURED`; this audit is the
  evidence the owner weighs — **it changes no gate, builds no
  intake, and prices nothing for any card.**
- **Written:** 2026-10-15, before any either-pitcher score was
  computed. Stage 2 of the MLB market-leg lane.
- **Question:** The engine's either-construction is a Cartesian
  product of the two starters' pools — independence given the
  marginals. On realized paired-starter history, how large is that
  construction's calibration error at the rung thresholds DK hangs,
  and how large is the dependence itself?

## 1. Construction under measurement (exact)

- Engine: `sportsedge/pitcher_joint_engine.py`
  `price_pitcher_market` at main
  `83e0c396a4761ea3de80583be5e61e8ca2e07f9a` (blob
  `00cba6f664e313b53ab0084e6f3f471a9d85b566`, identical to the Phase 2
  pin — see SPEC_M29 §1).
- The either branch (engine L208–213): states = Cartesian product
  of the two pools' values with product weights; the same
  empirical-Bayes posterior as the single-pitcher path; effective
  N = min of the two pools'. The audit calls this branch in the
  canonical configuration: features =
  `{"pitcher_a_history": [...], "pitcher_b_history": [...]}` — raw
  pools, no weights, no adjustments (the design package §3.1: the
  either branch consumes raw pools with none of the single-pitcher
  path's context adjustments — that is the construction as it
  exists, and it is the construction measured).
- Pools: the undercard/M29 pool semantics (same-season, strictly
  prior, ≤ 12 most recent starts, ≥ 5 required, sealed-window
  starts removed) for each starter independently.
- Rung events (the settlement layer's max/min reading,
  `either_pitcher_settlement.py` semantics):
  - **X+ rung:** at least one starter ≥ X — engine: market
    EITHER_PITCHER_*, side OVER, line X − 0.5.
  - **N-or-fewer rung:** at least one starter ≤ N — engine: side
    UNDER, line N + 0.5.
- Threshold grids (declared here): HA — X+ ∈ {5, 6, 7, 8, 9, 10},
  or-fewer N ∈ {2, 3, 4, 5}; BB — X+ ∈ {3, 4, 5, 6}, or-fewer
  N ∈ {0, 1, 2}; ER — X+ ∈ {3, 4, 5, 6}, or-fewer N ∈ {0, 1, 2}.
  **Honest gap, carried from the design package §2:** no capture
  on record pins DK's actual either-rung label text or prices for a
  specific fixture; these grids span the plausible rung range for
  each stat and are an evaluation grid, not a claim about any one
  board. Materiality is read off the grid (§5), not off a single
  rung.

## 2. Population

- A scored unit is a **game**: both starters independently in the
  undercard population (§1 pools satisfiable on the game's date,
  fixture start = a gamesStarted == 1 gameLog row for each), paired
  by StatsAPI `game_pk` from the same data transport as M29
  (seasons 2024 and 2025, regular season; fixtures inside the
  sealed window [2024-07-01, 2024-09-01) excluded, as are starts in
  the window from pools).
- Pair assembly is symmetric in the two starters (max/min events do
  not depend on which side is labeled A); the away starter is
  recorded as pitcher_a per the pair-entity convention
  `"<away_id>|<home_id>"` for the audit trail.
- Exclusions counted: `PAIR_SIDE_MISSING` (a game_pk with only one
  qualifying starter fixture), plus the inherited pool exclusions
  per side. No other exclusions are permitted.

## 3. Point-in-time audit

Each side's pool is strictly prior to the game date (production
collector semantics); the pair's realized stats enter only as
outcomes after both predictions are formed. Market prices never
enter (no either-pitcher market leg exists historically; DK's
either ladders are one-sided and were never archived).

## 4. Measurements (declared before results)

Per (stat, form, threshold), over the scored pairs:

- **Primary — calibration error of the independence
  construction:** mean engine either-probability, realized
  either-event rate, and their difference (predicted − observed, in
  probability points) with a 95% percentile CI, block bootstrap over
  ISO calendar weeks, 2,000 resamples, seed 20261015. Positive
  error = the construction overstates the buyable (yes-only) side —
  the direction the design package §3.2 predicts under positive
  dependence.
- **Dependence size, two estimators:**
  - (a) **Joint-exceedance ratio** at each X+ threshold: realized
    P(both starters ≥ X) divided by the mean over pairs of
    pA(X)·pB(X), where pA/pB are the engine's single-pitcher
    posterior exceedance probabilities from the same pools (the
    SPEC_M29 swept-CDF construction). Ratio > 1 = positive
    dependence at that threshold; CI by the same bootstrap.
  - (b) **Residual correlation:** per stat, Pearson and Spearman
    correlation across pairs of (realized − posterior mean) for
    the two starters, posterior means taken from the swept
    single-pitcher CDFs (E[X] = Σ_m (1 − F(m)) over the stat's
    undercard grid); CIs by the same bootstrap.
- Descriptive: per-pair Brier score of the engine either-probability
  (reported, not gated — there is no baseline either-probability to
  beat; the Fréchet bounds max(pA, pB) ≤ P(either) ≤ min(1, pA + pB)
  are reported beside the independence point value at each
  threshold so the owner can see where inside the identified
  interval the construction sits and where the realized rate sits).

## 5. Reading rule and verdict form

- **Verdict: DEPENDENCE_MEASURED** — a measurement report, not a
  pass/fail gate. The report states, per stat and form: the
  calibration error at every grid threshold with CIs, the two
  dependence estimates with CIs, and the pooled mean signed error.
- **Materiality reading (the lane's stated interpretation, declared
  before results; the ruling stays the owner's):** at a one-sided
  yes-only rung, an independence overstatement whose 95% CI lower
  bound exceeds **+2 probability points** is material — it is
  larger than the price precision at which such rungs are hung and
  it is systematic (same sign by construction under positive
  dependence), so it would manufacture apparent EV on exactly the
  side a bettor can buy. Errors whose CIs include 0 are reported as
  not distinguishable from zero on this sample — which is a
  statement about the sample, not proof of independence.
- Whatever the measurements say, the family's state after this
  audit is unchanged: `EITHER_PITCHER_DEPENDENCE_UNMEASURED` until
  the owner weighs this evidence. No intake, no pricing, no gate
  change is proposed by this lane.

## 6. Verification required before the measurements are reported

- **Pool parity:** the pair population is built by the same code
  path as M29; the M29 §6 parity requirement (25/25 pool equality
  vs the production source) covers this audit's pools — if M29's
  parity has not run on the identical evaluator lineage, it runs
  here first.
- **Event-semantics check:** on ≥ 10 pairs, the engine's either
  probability at one X+ and one or-fewer threshold is reproduced by
  an independent hand computation from the two pools (Cartesian
  product of the raw pool values with the engine's posterior
  formula re-derived from the single-pitcher path) to < 1e-9 — the
  audit measures the construction it thinks it is measuring.
- **Determinism:** fixed seed; re-runs reproduce results except
  timestamps.
