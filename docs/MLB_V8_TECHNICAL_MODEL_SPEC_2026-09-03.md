# SportsEdge MLB V8 Technical Model Spec — 2026-09-03

Status: **COMPANION SPECIFICATION — IMPLEMENTATION CONTRACT**

This document accompanies `docs/MLB_V8_HYBRID_BLUEPRINT_2026-09-03.md`. It defines the minimum quantitative and reproducibility requirements for MLB V8 probability generation, simulation, devig, calibration, context adjustments, and risk controls.

It does not certify any current market as validated or deployment-eligible.

## 1. Probability-generation architecture

SportsEdge MLB V8 is an ensemble/distribution system rather than a single heuristic score.

Each market family must identify:

- target variable
- training sample definition
- feature contract
- model class/version
- prior/shrinkage layer
- calibration transform
- simulation bridge, if applicable
- output probability or full distribution

The implementation may combine multiple submodels, but every durable prediction must resolve to one independent `Model_P` that does not incorporate current sportsbook line, public ticket split, handle split, sharp consensus, or handicapper opinion as a predictive feature unless that specific market model has been separately declared and validated as a market-informed model. The default SportsEdge MLB V8 doctrine is market-independent `Model_P`.

## 2. Feature provenance

Every model feature must be PIT-safe and tagged with:

- source/provider
- observation timestamp or effective timestamp
- ingestion timestamp when relevant
- event/player/team identity
- feature transformation version
- missingness state

Current-day or in-progress data may not enter a historical decision state merely because it is available at replay time.

## 3. Priors and shrinkage

Small-sample performance must be shrunk toward stable priors.

Examples include:

- pitcher platoon splits
- pitch-type performance
- hitter pitch-type performance
- umpire tendencies
- park/weather micro-effects
- manager hook behavior
- first-inning outcomes
- reliever recent-form estimates

Any market-specific model using an empirical rate must define either:

- Bayesian/empirical-Bayes prior and effective sample size, or
- an equivalent regularization/shrinkage mechanism.

Raw small-sample rates are not permitted as unbounded direct adjustments.

## 4. Starting pitcher state model

The starter state should be derived from PIT-safe components such as:

- K%, BB%, K-BB%
- whiff%, chase%, zone%, CSW where available
- batted-ball quality including barrel/hard-hit measures
- ground-ball/fly-ball profile
- pitch arsenal usage
- velocity, movement, extension, release-point stability
- platoon matchup
- opponent projected lineup
- recent workload
- expected pitch count
- manager hook behavior

Recent changes must be blended with longer-term talent estimates using minimum-sample and shrinkage rules. No single-start velocity or outcome change may become a full-strength adjustment without explicit anomaly/confirmation logic.

## 5. Hitter state model

Hitter state should include appropriately shrunk measures of:

- contact and strikeout skill
- walk/chase discipline
- xwOBA/wOBA-style quality
- ISO/power
- exit velocity/barrel/hard-hit characteristics
- platoon
- pitch-type matchup
- expected lineup slot
- expected plate appearances
- pinch-hit/removal risk where material

Confirmed lineup state supersedes projected lineup state. A late scratch requires re-evaluation of affected player and team markets.

## 6. Bullpen model

Bullpen strength must be represented as a game-state-dependent distribution rather than a single season ERA adjustment.

At minimum, the state should distinguish:

- high-leverage arms available
- high-leverage arms limited/unavailable
- recent pitch counts
- back-to-back or multi-day usage
- handedness composition
- baseline reliever quality
- expected leverage sequence

Full-game markets may use this state. First-five and first-inning markets must not inherit unnecessary late-game bullpen variance.

## 7. Run-distribution engine

The canonical game simulation should generate a coherent joint distribution of runs and player opportunities.

The simulation may be inning-level, plate-appearance-level, or hybrid, but must preserve dependencies relevant to supported markets, including:

- starter duration
- bullpen transition
- batting-order cycling
- team scoring covariance
- game state and extra innings where applicable

A single coherent simulation should be preferred where practical so that ML, RL, totals, team totals, F5 and supported props do not contradict one another because of incompatible assumptions.

## 8. Monte Carlo minimums and seeds

Minimum production simulation counts:

- ML / run line / total / F5: **100,000**
- NRFI/YRFI: **100,000** first-inning trials or analytically equivalent calculation
- pitcher/hitter props: **100,000** player-outcome trials when simulation-derived
- HR probability: **200,000** plate-appearance/game exposure trials when simulation-derived
- First HR / SGP joint outcomes: **250,000** minimum unless convergence diagnostics demonstrate a lower count produces equivalent precision

Validation runs must record a deterministic seed or deterministic seed derivation from immutable prediction identity.

For any reported probability `p`, Monte Carlo standard error should be available or derivable. If sampling error is too large relative to the market edge, the wager must be downgraded or passed.

## 9. Convergence requirement

A simulation-derived wager must pass a convergence check.

At minimum, compare independent deterministic substreams or staged cumulative estimates. The final estimate must remain within a market-specific tolerance of the prior checkpoint.

Recommended default tolerance:

- ±0.25 percentage points for primary two-way markets
- ±0.40 percentage points for props
- ±0.60 percentage points for low-probability HR/First-HR outcomes

If convergence fails, increase simulation count or emit `DATA_GAP` / `SIMULATION_UNSTABLE`.

## 10. Reproducibility tolerance

Given identical:

- input snapshot
- model SHA
- feature-contract SHA
- policy SHA
- simulation configuration
- deterministic seed

probability outputs must reproduce within:

- exact equality for deterministic analytic outputs, or
- ±0.01 percentage points for deterministic seeded Monte Carlo outputs, absent documented floating-point/platform variance.

A wider reproducibility tolerance requires an explicit versioned exception.

## 11. Devig specification

### Two-sided primary method

`MULTIPLICATIVE_V1`

For two outcomes with implied probabilities `q1` and `q2`:

`p1 = q1 / (q1 + q2)`

`p2 = q2 / (q1 + q2)`

The implementation must retain original odds, raw implied probabilities, overround, method ID, and resulting no-vig probabilities.

### Fallbacks

If a market lacks both sides at the same sportsbook/timestamp, do not fabricate a same-book no-vig probability. A separately identified consensus or paired quote may be used only under a declared evidence rule and must retain provider provenance.

### N-way markets

First HR and any other N-way market must use a market-specific N-way normalization or structural simulation benchmark. Two-sided `MULTIPLICATIVE_V1` is invalid for these markets.

## 12. Fair odds and EV

For binary outcomes:

- fair decimal odds = `1 / Model_P`
- convert to American odds using the canonical odds utility
- EV at offered decimal odds `d` = `Model_P * d - 1`

For pushes/void-capable markets, EV must explicitly include push probability and settlement rules.

No market may use a binary EV formula if push mass is material and not included.

## 13. Calibration

Each market family must use a frozen calibration method fitted only on training/calibration data prior to the untouched forward holdout.

Permitted examples include:

- logistic/Platt calibration
- isotonic calibration where sample size supports it
- beta calibration

The chosen method must be versioned per market family. Calibration may not be re-fit using the active holdout.

Required evaluation includes:

- calibration slope
- calibration intercept
- ECE
- reliability/bucket diagnostics
- Brier score
- log loss

## 14. Market benchmark comparison

Where a valid no-vig market benchmark exists, SportsEdge must compare calibrated predictions to the contemporaneous no-vig market on the same examples.

Required metrics include:

- Brier score differential
- log-loss differential
- CLV
- after-vig ROI

The market benchmark must use the same prediction cutoff and exact event/market identity. Later prices may not contaminate the decision-time benchmark.

## 15. First HR model

FIRST_HOME_RUN must be modeled structurally.

For each simulated game:

1. simulate plate appearances in batting-order sequence;
2. simulate HR occurrence using hitter-specific hazard conditional on pitcher, park, weather and exposure state;
3. stop at the first home run;
4. assign probability mass to the hitter who hit it;
5. if no HR occurs, assign mass to `NO_HOME_RUN`.

The resulting probabilities across all hitters plus `NO_HOME_RUN` must sum to 1 within numerical tolerance.

Calibration and benchmark evaluation must be N-way appropriate.

## 16. SGP dependency specification

Maintain a versioned dependency registry.

At minimum, dependencies should be explicitly recognized for:

- favorite ML ↔ opponent team total under
- pitcher Ks ↔ opponent scoring
- pitcher outs ↔ pitcher Ks
- hitter HR ↔ hitter total bases
- hitter HR ↔ team total
- correlated hitters through shared run environment
- game total ↔ team totals

If joint simulation exists, use the empirical joint probability from simulations.

If joint simulation does not support the dependency, the SGP must not be priced by naïve marginal multiplication. Mark the combination unsupported.

## 17. Weather effect controls

Weather adjustments must use stadium-relative and game-time state, not generic city weather.

Inputs may include:

- temperature
- humidity/dew point
- air density proxy
- wind speed and stadium-relative direction
- precipitation/rain-delay risk
- roof status

Adjustments must be bounded and shrunk. Unknown roof status cannot be silently treated as open or closed.

## 18. Umpire effect controls

Only confirmed plate umpires may be used.

Umpire effects must be shrunk toward league average based on sample size. They may modify called-strike, walk, strikeout or run-environment assumptions, but must not dominate the base pitcher/hitter model.

If the umpire is unconfirmed, no umpire adjustment is applied.

## 19. Context-source independence

Context does not alter `Model_P` in the default architecture.

For context scoring, source independence is determined by the underlying data provider/feed.

Examples:

- Action reposting DraftKings splits + an X post reposting the same DraftKings split = one underlying signal.
- BetMGM handle + Circa line movement = two distinct underlying market signals if independently sourced.

A `HARD_MARKET_SIGNAL` requires:

- identifiable primary provider or book
- specific market
- current timestamp/window
- explicit observed statistic or line movement

A `STRONG CONTEXT LEAN` should require at least two materially independent supporting signals, with no unresolved high-severity contradiction.

## 20. Risk controls

Default stake framework: **0.25 Kelly**, subject to hard caps.

Recommended production caps until market-specific validation supports alternatives:

- maximum single wager: 1.5% bankroll
- maximum game exposure: 3.0% bankroll
- maximum correlated cluster: 3.5% bankroll
- maximum team exposure across same slate: 4.0% bankroll
- maximum daily MLB risk: 8.0% bankroll

For markets not deployment-eligible, stake cap should be lower than OFFICIAL-eligible markets. Suggested default maximum for `MODEL LEAN — NOT PROMOTED`: 0.75% bankroll, absent a user-selected flat-stake override.

Context-only plays must never receive Kelly-derived stake from a nonexistent `Model_P`.

## 21. Drawdown dampener

Risk sizing may be reduced during drawdown without changing model probabilities or promotion criteria.

Suggested deterministic schedule based on peak-to-current bankroll drawdown:

- <5% drawdown: 1.00x base stake
- 5–10%: 0.75x
- 10–15%: 0.50x
- >15%: 0.25x and require explicit review before restoring normal size

This is a risk-control layer only.

## 22. Promotion gates

The frozen Truth Gate policy file remains authoritative. This document does not override configured thresholds.

At minimum, promotion evaluation must be market-specific and include:

- minimum sample size
- untouched chronological holdout
- calibrated probability quality
- Brier/log-loss comparison to no-vig market
- CLV threshold with uncertainty requirement
- ROI after vig
- edge-floor stability
- evidence completeness
- reproducibility

No pre-hotfix qualification may be grandfathered if it cannot satisfy the current evidence contract.

## 23. Temporal integrity

For forward and replay qualification:

`feature_observation_or_availability_time <= decision_time`

For replay quote selection:

`EARLY_ONLY_AT_OR_BEFORE_TARGET`

A later observation cannot be substituted for a missed target quote.

Default Statcast acquisition excludes the current MLB local calendar date. Event-level PIT checks remain stricter and govern any feature used in replay/validation.

## 24. Failure semantics

Canonical fail-closed statuses include:

- `DATA_GAP`
- `STALE_INPUT`
- `IDENTITY_UNRESOLVED`
- `SIMULATION_UNSTABLE`
- `PROVIDER_BLOCKED`
- `MISSED_OR_BLOCKED`
- `NOT_MODEL_P`
- `NOT_PROMOTED`

The engine must prefer a transparent non-bet over an unsupported probability.

## 25. Technical-spec change control

Canonical name: **SportsEdge MLB V8 Technical Model Spec**

Version: **2026-09-03**

Any material change to feature semantics, devig, model family, calibration, simulation process, risk controls, temporal-integrity rules, or promotion evaluation requires a new version and change note.
