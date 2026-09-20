# NFL Unified Market Probability Contract

Status: implementation contract only. No promotion, staking, Truth-Gate pass, OFFICIAL authority, or evidence backfill is created by this document.

## Objective

SportsEdge NFL uses one common decision pipeline for every supported market:

independent projection -> outcome distribution / simulation -> Model_P -> paired sportsbook price -> no-vig fair probability -> edge -> EV -> canonical Truth Gate -> OFFICIAL or non-authoritative Model_P output.

A probability is useful before promotion, but it must never be mislabeled OFFICIAL.

## Priority

1. Spread
2. Total
3. Moneyline
4. Anytime touchdown scorer
5. Team totals
6. Passing / rushing / receiving props
7. Period and alternate markets
8. Kicker / defensive props

## Required output contract

Every priced candidate must bind:
- sport, season, week, game_id, kickoff, market_id and selection
- model/version/artifact SHA and feature snapshot timestamp
- simulation RNG/version/seed and simulation count when simulation-derived
- Model_P
- exact sportsbook, odds, line, quote timestamp and receipt identity
- opposite-side paired quote where a two-way no-vig calculation is required
- raw implied probability, no-vig probability, edge in percentage points, model fair odds and EV
- Truth-Gate disposition and explicit authority label

Allowed authority labels:
- OFFICIAL: only canonical Truth Gate authorizes it.
- MODEL_P_NOT_OFFICIAL: probability mechanics are valid but promotion/evidence is incomplete.
- BLOCKED: required model, distribution, quote, evidence, freshness, identity or governance condition is absent.

## Independence

Market prices are comparison data, not an implicit substitute for the independent projection. Any market-derived feature used inside Model_P must be separately preregistered, PIT-safe and validated.

News, weather, inactives, lineup/role changes and other contextual data may update a projection only through timestamped PIT-safe features. Capper opinion is commentary only and cannot create Model_P.

## Simulation

Use deterministic/versioned simulation with recorded seed and implementation/artifact identity. Default production target is 50,000 paths where computationally practical. Simulation count alone does not establish validity.

## Market requirements

### Spread / total
Produce cover/over/under probabilities from the validated game distribution. Integer lines require validated discrete push mass; otherwise BLOCKED.

### Moneyline
Requires a validated win/tie/overtime-capable score distribution. Do not infer ML probability from spread probability alone.

### Anytime touchdown
ATTD is priority immediately after ML. The player-level distribution should use PIT-safe opportunity/role inputs including active status, snaps/routes, carries/targets, red-zone and goal-line opportunity, receiving role, team scoring environment, opponent context, game script and weather where relevant. Correlated teammate opportunity must be represented rather than treating scorers as independent Bernoulli events.

Output is the simulated probability of >=1 touchdown for that player. Missing confirmed participation/role inputs near kickoff must fail closed according to the market's frozen policy.

### Other props
Each prop family requires its own validated outcome distribution and calibration evidence. Do not derive a probability merely by applying a generic normal distribution to a point projection unless that distribution has been prospectively validated for that market family.

## Market comparison

Convert sportsbook prices to implied probabilities. Remove vig using the frozen method appropriate to that market structure. Keep book identity intact; do not construct synthetic opposite sides across books unless a frozen policy explicitly permits it.

edge_pp = Model_P - no_vig_market_probability

EV must be computed from Model_P and the actual offered payout. Edge and EV are descriptive model outputs, not promotion evidence.

## Freeze and grading

Pregame projections remain live only through the frozen update policy. Once the required final lineup/inactive window is reached, persist the immutable prediction/quote receipt used for grading. No historical reconstruction may be relabeled as prospective evidence.

## Governance

Canonical Truth Gate remains the only OFFICIAL authority. This contract must not:
- set deployed=true
- set eligible=true
- manufacture calibration/CLV/ROI evidence
- backfill missed evidence windows
- transfer promotion authority between models or markets
- authorize Kelly/staking when Truth Gate is blocked

When evidence is insufficient, emit MODEL_P_NOT_OFFICIAL or BLOCKED with the precise reason.


## ATTD research-feature layer

SportsEdge combines the shared-path touchdown probability engine with transparent research diagnostics inspired by publicly described ATTD research workflows. These diagnostics are inputs/candidate features, not copied external scores and not independent evidence.

Candidate PIT-safe feature families:
- expected touchdowns (xTD) versus actual touchdowns, with a descriptive TD-debt residual
- opportunity by field zone: goal line (0-5), red zone (6-20), fringe (21-40), and open field
- carries, targets and xTD within each zone
- snap share, route participation, target share, rush share, touches and goal-line share
- team scoring environment / independent expected team points
- opponent-adjusted touchdown environment
- coverage-shell splits where source identity and pregame availability are valid
- box-count splits for rushers where source identity and sample support are valid
- weather, venue, rest/travel, injury and inactive context under the PIT contract

### Composite research score

A Venom-style single scan/ranking number may be useful for the board, but SportsEdge must build and validate its own score. It may summarize SportsEdge features for ranking only; it must not be substituted for Model_P, edge, EV, calibration evidence, or Truth-Gate authority. External proprietary scores/probabilities/weights must never be copied into Model_P.

Suggested output fields are `attd_model_p`, `expected_tds`, `actual_tds_prior`, `td_debt`, zone opportunity splits, coverage/box diagnostics, role/volume diagnostics, market fair probability, edge, EV, and authority status.

### Anti-leakage rules

Actual TDs and games-since-last-TD must be cutoff before the target kickoff. TD debt is descriptive unless a preregistered candidate proves incremental out-of-sample value; a player being "due" cannot itself increase Model_P. Coverage/box splits require minimum-sample handling and shrinkage before predictive use. Opponent tendencies must be derived only from prior games. Public research tools, videos, social posts and capper tags are context/feature inspiration only and cannot vote on a play.
