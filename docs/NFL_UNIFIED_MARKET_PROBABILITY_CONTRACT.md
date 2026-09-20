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


## Prop reopening and evidence authority

NFL player props are deliberately reopened for **research/EXPERIMENTAL implementation only**. This does not revoke the prior NO_ENGINE production freeze, does not move prop markets ahead of the frozen NFL game-market forward clocks, and does not authorize prospective promotion evidence. The production registry remains NO_ENGINE until a separate, explicit, frozen policy change is reviewed and merged.

A coherent probability read-out is EXPERIMENTAL, not automatically a validated Model_P. A market/family may be labeled VALIDATED_MODEL only after its preregistered historical/PIT evaluation and calibration gates pass. OFFICIAL remains downstream of prospective Truth-Gate evidence.

For the 2026 evidence lane, spread, total and moneyline remain the active game-market priority. ATTD and other props stay research-only until their family policy, quote methodology, capture burden and validation contract are frozen.

## Prop-family preregistration

Before any prop-family observation can count toward promotion evidence, freeze:
- family identity and shared latent component
- eligible selections and logging universe
- feature/artifact/model identities
- historical train/validation windows and minimum sample rules
- scoring metrics and calibration gates
- sportsbook quote structure and vig-removal methodology
- opener/final capture windows and missing-quote disposition
- settlement source/rules
- prospective evidence unit and minimum evidence requirement

Log the full eligible candidate universe before ranking/filtering. The research score may sort presentation but cannot decide which eligible rows are persisted.

Evidence is counted by shared component/family rather than pretending correlated derivative markets are independent confirmations.

## ATTD quote policy prerequisite

ATTD must fail closed for promotion evidence while only a one-sided Yes quote is available under a paired-quote devig policy. Do not synthesize a No side or infer vig from another book. A one-sided or N-way fair-value method must be preregistered and frozen before observing its validation/promotion results. Until then, offered-price EV may be displayed only under an explicitly non-authoritative research label and must not be described as no-vig edge.

## Shared touchdown allocation

ATTD simulation must conserve the parent team scoring path. For every simulated team offensive touchdown, assign the scorer through the team's conditional player-share distribution. Player TD totals therefore cannot exceed the simulated team's attributable offensive TD total. Participation, role and teammate shares are resolved before allocation; missing mass or unresolved identity fails closed rather than creating an anonymous probability shortcut.

## Position-level ATTD evaluation

Evaluate ATTD with proper scoring/calibration both overall and separately for at least RB, WR and TE. Record sample count, base rate, log loss, Brier score, calibration intercept/slope and ECE by position. A pooled pass cannot conceal a failing required position segment. Any minimum-sample exception must be frozen before evaluation.

## Market-blind scoring environment

Any team expected-scoring feature entering ATTD Model_P must come from SportsEdge's independent market-blind football distribution. Sportsbook spreads, totals, implied team totals, prices or consensus lines are prohibited Model_P inputs unless a future separately preregistered model explicitly validates them. They remain comparison data.

## Leakage invariance

ATTD feature tests must perturb every current-game label and every post-kickoff field available to the builder, individually and in randomized combinations, and assert the complete pregame feature vector is byte-equivalent. Coverage-shell and box-count features additionally require documented historical availability over the frozen train/validation window. If coverage is insufficient, those fields remain research diagnostics or are excluded from the frozen candidate rather than silently shortening the holdout.


## TD allocation residual and score-type separation

Player TD allocation must retain an explicit residual/other-player bucket for eligible offensive touchdowns whose scorer is outside the modeled candidate set. Candidate shares are never renormalized to 100% merely because the candidate list is incomplete. The residual bucket participates in every simulation and is reported in diagnostics.

Only offensive TD events eligible under the sportsbook's player-TD settlement contract enter offensive scorer allocation. Defensive touchdowns and special-teams/return touchdowns remain separate event paths and cannot leak into rushing/receiving scorer shares. Any ambiguous event type fails closed until settlement mapping is resolved.

## Reproducible randomized leakage tests

Every randomized leakage-invariance test must use an explicit recorded RNG implementation/version and seed. On failure, the seed and perturbed field set must be emitted so the exact case can be replayed. CI must not use ambient/random system entropy for these tests.

## Final-head freeze

All policy hashes, implementation hashes and artifact bindings in this stacked work are provisional until the final merge candidate is known. Immediately before merge, regenerate the freeze/attestation against the actual PR head and require the recorded SHA-256 identities to match that exact head. A prior intermediate commit, including c3e0a93, cannot serve as final freeze authority after subsequent changes.


## Sequence-market structural blocker

The current structural Engine A event generator is **not possession ordered**: it samples each team's scoring events independently and then sorts them by period/clock. Therefore first-score, first-TD and race-to-N readouts are mechanics-only EXPERIMENTAL diagnostics and must not be labeled VALIDATED_MODEL or accrue promotion evidence from this generator.

Before sequence markets can validate, the parent simulator must model opening possession (coin-toss/receive/defer policy), alternating possession transitions, halftime possession flip, drive termination/scoring and overtime possession rules. Validate the resulting first-score rate conditional on opening receiver against a frozen historical benchmark. Event-order plausibility alone is insufficient.

## Key-number dependency

Winning-margin bands, spread derivatives and any market reading exact margin mass inherit the known key-number validation requirement. Until held-out mass around NFL key margins (including 3 and 7) passes the frozen behavioral test, these readouts carry a `KNOWN_KEY_NUMBER_MISCALIBRATION` experimental disposition and cannot be promoted.

## Sequence settlement freeze prerequisite

Settlement is part of each market identity and must be sourced from the target sportsbook's frozen rules before evidence begins. The family policy must explicitly encode:
- whether safety, defensive TD and return/special-teams TD count for first score;
- first-TD treatment when no touchdown occurs;
- race-to-N treatment when neither team reaches N;
- player did-not-play/void handling and participation cutoff;
- overtime inclusion/exclusion where applicable.

First-TD remains N-way/one-sided and promotion-blocked until its preregistered fair-value/devig methodology is frozen. No settlement assumption in research code grants evidence authority.
