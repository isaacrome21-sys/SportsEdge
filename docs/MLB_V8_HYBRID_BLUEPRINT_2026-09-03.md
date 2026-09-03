# SportsEdge MLB V8 HYBRID Blueprint — 2026-09-03

Status: **CANONICAL OPERATING DOCTRINE**

This document defines how SportsEdge MLB V8 operates across AUTOMATIC, HYBRID, and MANUAL execution without changing model semantics. It does **not** promote any market, change Truth Gate thresholds, or make any market `eligible=true`.

## 1. Core doctrine

SportsEdge separates four layers:

1. **MODEL** — the independent SportsEdge probability, `Model_P`.
2. **MARKET** — executable sportsbook price and no-vig market probability.
3. **EDGE / EV** — comparison of `Model_P` to the no-vig market, including fair price, EV, and stake sizing.
4. **CONTEXT** — news, betting splits, line movement, weather, injuries, lineup information, social discovery, matchup notes, and other external information.

Context may strengthen, weaken, invalidate, or defer a wager. Context must never manufacture `Model_P`.

Only the exact deployed/validated market artifact may be called **SPORTSEDGE OFFICIAL**, consistent with `docs/market_status_semantics.md`.

## 2. Execution modes

### AUTOMATIC
Scheduled/CI execution performs acquisition, normalization, modeling, evidence capture, output, and persistence when infrastructure is healthy.

### HYBRID
Default day-to-day mode. User sportsbook screenshots/lines are combined with automatically acquired public information and SportsEdge model outputs. Automation failure must not prevent a disciplined betting card when sufficient current inputs are available.

### MANUAL
Used when automation and/or public providers are degraded. User-supplied current lines and verifiable inputs may be used, but missing inputs remain explicit `DATA_GAP`s. No inference or silent substitution is allowed.

The three modes differ only in input acquisition and execution mechanics. They do not change model semantics, Truth Gate policy, or evidence rules.

## 3. Betting Engine vs Validation Engine

SportsEdge maintains a hard separation between:

- **Betting Engine** — finds the best current wagers using the best available current data.
- **Validation Engine** — proves whether a market/version deserves deployment eligibility using strict chronological point-in-time evidence.

A HYBRID bet may be actionable while remaining `MODEL LEAN`, `CONTEXT LEAN`, or `STRONG CONTEXT LEAN`. It does not become validation evidence unless the exact forward evidence contract is satisfied.

## 4. Canonical market sweep

`RUN IT MLB` means a full HYBRID scan of available markets, including:

- moneyline
- run line / spread
- full-game totals
- team totals
- first-five moneyline, spread, and total
- NRFI / YRFI
- pitcher strikeouts, outs, earned runs, hits, walks, win props
- hitter hits, total bases, home runs, RBI, runs, H+R+RBI, walks, stolen bases
- first-home-run market
- alternate lines
- same-game parlays where joint simulation is supported
- sportsbook promotions and boosts

No market should be omitted merely because another market already produced a bet.

## 5. Current-data workflow

For every game, bind all evidence to a canonical event identity. Preferred identifiers include the provider game PK plus normalized `YYYY-MM-DD_AWAY_HOME` display identity. Start time must be stored separately and never used as the sole event key.

Acquire/verify, where available:

- probable and confirmed starters
- projected and confirmed starting lineups
- injuries, scratches, call-ups, roster changes
- catcher and platoon context
- venue, roof/dome status, playing environment
- weather and stadium-relative wind
- bullpen availability/workload
- umpire status when confirmed
- odds and line history
- book-by-book differences
- public ticket and money/handle splits
- relevant public social/beat-writer reporting

Projected information must be explicitly labeled as projected. Unknown data remains unknown.

## 6. Odds and no-vig market layer

The execution book is the sportsbook at which the user can actually wager. External books/aggregators are used to judge price quality, line movement, consensus, and market disagreement.

For ordinary two-sided markets, the canonical primary devig method is:

`MULTIPLICATIVE_V1`

The exact method must be recorded with the evidence. Market families for which a two-sided multiplicative devig is structurally invalid — especially N-way markets such as FIRST_HOME_RUN — must use a market-specific method and must never be certified using the two-way benchmark.

## 7. Model families

SportsEdge MLB V8 may produce independent distributions/probabilities for:

- game winner
- run margin
- total runs
- first-five outcomes
- team totals
- NRFI/YRFI
- pitcher outcomes
- hitter outcomes
- home run outcomes
- first-home-run outcomes

Model families may share coherent latent game-state simulations, but each market remains separately validated and separately eligible.

## 8. Monte Carlo and reproducibility

Monte Carlo outputs must be reproducible for qualifying evidence.

Every durable prediction must record:

- model version / model SHA
- feature-contract SHA
- policy SHA
- simulation configuration
- deterministic seed or deterministic seed derivation
- simulation count
- input snapshot/evidence identity

Given the same frozen inputs, model artifact, policy, and seed, the result must reproduce within the declared numerical tolerance. Failure of reproducibility disqualifies Tier-A validation evidence.

Simulation counts are market-specific and defined in the companion Technical Model Spec. No production or validation claim may rely on an unspecified simulation configuration.

## 9. Starting pitcher and bullpen state

Starting-pitcher modeling should incorporate appropriately shrunk and PIT-safe information such as:

- strikeout, walk, contact and command indicators
- batted-ball quality
- pitch arsenal, usage, velocity, movement and whiff characteristics
- platoon effects
- recent changes subject to minimum-sample/shrinkage rules
- workload and expected pitch count
- manager removal tendencies

Bullpen state is modeled separately from starter state and may affect full-game markets differently from first-five and early-inning markets.

## 10. Lineup and hitter state

Before lineup confirmation, use `PROJECTED_LINEUP`. After official confirmation, use `CONFIRMED_LINEUP`.

Late scratches invalidate stale player-market evaluations unless the engine explicitly re-runs using the new lineup state.

Expected plate appearances and batting-order uncertainty must be modeled for hitter props.

## 11. NRFI / YRFI

NRFI/YRFI must be modeled as a first-inning run-event problem rather than by using season NRFI rates alone. Inputs may include top-of-order quality, pitcher command, platoon, park/weather, expected first-inning pitch mix, walk/contact/homer hazards, and confirmed lineup state.

NRFI/YRFI remains independently validated from full-game totals.

## 12. Home run and First HR

Ordinary HR markets require hitter-specific home-run probability using plate-appearance exposure, pitch/hitter matchup, batted-ball skill, park, weather and pitcher HR hazard.

FIRST_HOME_RUN is an N-way market. It must explicitly include `NO_HOME_RUN` probability and be modeled as an ordered joint event process. Two-sided devig, binary calibration or a two-way benchmark is invalid for this market.

## 13. SGP dependency control

Same-game parlay probabilities must come from joint simulation or an explicitly declared dependency model. Marginal probabilities must never be multiplied blindly when legs are materially dependent.

Maintain a dependency graph/correlation registry for common relationships such as:

- pitcher strikeouts vs opponent team total
- pitcher outs vs game script
- hitter HR vs team total
- favorite side vs opponent scoring
- correlated hitter markets

Unsupported dependencies must result in `DATA_GAP` or a non-playable SGP, not an independence assumption disguised as precision.

## 14. Context provenance and independence

Context sources are classified by their underlying data provenance, not publisher/logo.

Examples:

- A public X post relaying BetMGM handle data inherits provenance `BETMGM`.
- Two sites relaying the same sportsbook feed count as one underlying HARD MARKET signal.
- X/social is primarily a discovery layer unless the originating account itself is the primary source.

Context categories include:

- `HARD_MARKET_SIGNAL`
- `SOFT_MARKET_SIGNAL`
- `NEWS_SIGNAL`
- `STATISTICAL_MATCHUP`

A HARD MARKET SIGNAL requires an identifiable primary market/provider source and current timestamp. Multiple HARD signals require provider/feed independence, not merely multiple publishers.

## 15. Weather and umpire adjustments

Weather, park, and umpire inputs are modifiers rather than primary model drivers. Their effect sizes must be quantitatively bounded and documented in the Technical Model Spec or associated lookup/configuration tables.

Unknown roof or umpire state remains unknown. No implied confirmation is allowed.

## 16. Risk and staking

SportsEdge uses fractional Kelly only after passing all market-specific decision constraints. Full Kelly is not the production default.

Risk controls include:

- maximum daily exposure
- maximum game exposure
- maximum team exposure
- maximum player exposure
- maximum market-family exposure
- correlation-cluster exposure cap
- promotion-status-aware stake cap
- drawdown dampener

Losing streaks or drawdown may reduce stake sizing. They must never alter `Model_P`, calibration, historical evidence, or Truth Gate thresholds.

No number of desired bets overrides risk caps.

## 17. Promotions

Promotions/boosts change payout economics and therefore EV, but do not alter `Model_P`.

A boost may make a previously marginal price attractive. It does not bypass deployment eligibility, validation, data-quality, or stale-input checks, and it cannot create OFFICIAL status.

## 18. Forward evidence contract

Every forward validation candidate requires an exact decision snapshot and exact close snapshot, or an explicit terminal status.

Required states include:

- `DECISION_CAPTURED`
- `CLOSE_CAPTURED`
- `PAIRED`
- `MISSED_OR_BLOCKED`

If a capture is missed, the system must record `MISSED_OR_BLOCKED` with reason such as:

- `RUNNER_UNAVAILABLE`
- `PROVIDER_TIMEOUT`
- `ODDS_UNAVAILABLE`
- `IDENTITY_UNRESOLVED`
- `LINEUP_UNCONFIRMED` when the policy requires confirmation

Missing forward evidence is never reconstructed from a later quote.

## 19. Replay PIT rule

Historical/replay qualification uses one-sided tolerance:

`EARLY_ONLY_AT_OR_BEFORE_TARGET`

A quote at or before the target may qualify if all other requirements pass. A quote after the target never qualifies merely because it is close in clock time.

Tier-A replay evidence requires exact proof of:

- observation timestamp
- event identity
- market identity
- target timestamp
- provider/source
- code/model/policy SHA as required by the evidence contract
- evidence hash / durable identity

Pre-hotfix records are not grandfathered into qualification. Qualification must be determined under the current frozen policy using the actual historical evidence.

## 20. Temporal integrity and Statcast

Default Statcast acquisition excludes the current MLB local calendar date as a conservative anti-leakage guard.

For any PIT feature, the stronger rule is:

> only information with an observation/event availability timestamp at or before the decision timestamp may enter the feature state.

A game having started before the decision timestamp is not by itself sufficient to make all game-derived information PIT-safe. Event-level and provider-availability timing govern qualification.

## 21. Truth Gate and eligibility

Promotion is market-specific. A market can become eligible only when its exact frozen model/version passes the declared forward gates.

Evaluation includes, as applicable:

- sample-size requirements
- chronological untouched holdout requirements
- calibration slope/intercept
- ECE
- Brier score
- log loss
- comparison to no-vig market baseline
- mean no-vig CLV and uncertainty/t-stat requirement
- ROI after vig
- edge-floor/bucket stability
- reproducibility and evidence completeness

Short-term win/loss records cannot promote a market.

All markets remain `eligible=false` until genuine gates pass.

## 22. User-facing governance labels

Canonical labels:

- `SPORTSEDGE OFFICIAL` — only when deployment eligible and current wager qualified.
- `MODEL LEAN — NOT PROMOTED` — independent `Model_P` exists but the market/version is not eligible for OFFICIAL deployment.
- `STRONG CONTEXT LEAN — NOT Model_P`
- `CONTEXT LEAN — NOT Model_P`
- `PASS`
- `DATA_GAP`

These labels must not be blurred in prose.

## 23. Machine-readable RUN IT record

Each selection record must carry at minimum:

- blueprint version
- event id / provider game id
- game start timestamp
- decision timestamp
- execution book
- market and selection
- line and price
- `Model_P` when available
- no-vig method and no-vig probability when valid
- fair price
- edge
- EV
- stake / Kelly fraction
- governance label
- context provenance list
- model SHA
- feature-contract SHA
- policy SHA
- evidence status
- close timestamp/price when later available
- CLV when paired

A standardized schema is defined separately and must fail closed on missing fields required for the given governance state.

## 24. Failure hierarchy

If GitHub/scheduled infrastructure fails:

1. use verifiable public web data plus user sportsbook evidence;
2. execute current SportsEdge model components where inputs are sufficient;
3. preserve missing inputs as explicit gaps;
4. emit `DATA_GAP` when missing data materially prevents a defensible current prediction;
5. emit `MISSED_OR_BLOCKED` for validation evidence when the exact capture contract was not met.

Operational resilience may preserve the Betting Engine. It may never fabricate Validation Engine evidence.

## 25. Canonical RUN IT meaning

`RUN IT MLB` means:

> Full SportsEdge MLB V8 HYBRID slate scan, all supported current markets, current odds, starters/lineups, injuries/news, weather/park, bullpen state, market movement, betting splits, public social/news discovery, matchup engine, independent Model_P/Monte Carlo outputs where available, no-vig/EV/fair-price/Kelly, correlation/exposure controls, and a ranked playable card with game times and explicit governance labels.

## 26. Change control

Canonical name: **SportsEdge MLB V8**

Blueprint version: **2026-09-03**

Any production change to semantics, evidence qualification, devig, model family, promotion gate, or governance labels requires a new version/change record. Documentation changes cannot themselves promote a market.
