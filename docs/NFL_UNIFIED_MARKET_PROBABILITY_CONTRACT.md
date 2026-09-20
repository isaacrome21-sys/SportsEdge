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


## Possession engine challenger isolation

The possession-ordered simulator is a **separate challenger**. It must not replace, mutate, refit, or silently feed the generator/model identity used by the frozen 2026 spread/total/moneyline evidence lane. All 2026 game-market confirmation captures, scoring, CLV and Truth-Gate accounting remain bound to their existing frozen model/artifact identities.

The challenger receives its own implementation identity, frozen policy, artifact hashes, validation ledger and—only after passing preregistered structural validation—a separately authorized prospective evidence ledger. Any future replacement of the incumbent requires an explicit frozen comparison/replacement protocol; no mid-season authority transfer is permitted.

### Challenger path contract

One ordered possession path is the source of truth for every challenger readout. It must represent:
- opening kickoff/receive/defer resolution and opening possession;
- alternating possession transitions;
- halftime possession flip;
- clock consumption, end-of-half behavior and two-minute state;
- score/time-dependent fourth-down and pace behavior;
- regulation and explicit overtime possession rules;
- offensive, defensive and special-teams scoring as distinct event types;
- player TD attribution plus residual/other-player mass on the same parent path.

First score, first TD, race-to-N, team/player TD totals, final margin and totals must all be deterministic slices of that same path.

### Structural validation before market validation

No challenger market probability is trusted until held-out structural tests pass under a frozen historical window. At minimum record:
- possessions per game distribution;
- opening-drive scoring rate;
- first-score rate conditional on opening-kickoff receiver;
- drive outcome mix (TD, FG, punt, turnover, downs, end-half/game and modeled special outcomes);
- final margin mass at 3, 7 and 10, with preregistered tolerances;
- total-points distribution/calibration;
- score/time-state behavioral diagnostics, including trailing/leading late-game decisions.

Failure of a required structural gate blocks every downstream challenger market that depends on it. Passing mechanics tests alone cannot create VALIDATED_MODEL, promotion evidence or OFFICIAL authority.


## Possession challenger preregistered tuning/holdout protocol

This protocol is frozen before challenger implementation begins.

### Data partition

- Development/calibration seasons: **2016-2019 and 2021-2023**.
- 2020 is an **exception/sensitivity season only** because of the materially unusual pandemic attendance/home-field environment. It cannot be used to tune parameters or rescue a failed primary gate.
- Primary untouched structural holdout: **2024-2025 regular seasons**.
- 2026 is prospective only and cannot be used for challenger tuning or retrospective structural acceptance.
- No parameter choice, tolerance, feature, rule or metric may be changed after inspecting 2024-2025 challenger results within an attempt. Any such change consumes the next attempt; holdout results from prior attempts remain permanently recorded.

### Structural acceptance bands

Compute empirical references from the frozen 2024-2025 holdout and compare challenger simulation to those references with the same game/team conditioning. Required gates:
- mean possessions per team-game: absolute error <= **0.50 possessions**;
- opening-drive scoring rate: absolute error <= **3.0 percentage points**;
- first-score probability for the opening-kickoff receiver: absolute error <= **3.0 pp**;
- drive outcome shares for TD, FG, punt, turnover, turnover-on-downs and end-half/game: each absolute error <= **3.0 pp**;
- absolute final-margin mass at exactly 3: error <= **2.0 pp**;
- absolute final-margin mass at exactly 7: error <= **2.0 pp**;
- absolute final-margin mass at exactly 10: error <= **1.5 pp**;
- mean total points per game: absolute error <= **2.0 points**;
- total-points distribution: simulated vs empirical quantiles at 10/25/50/75/90 percentiles each within **3.0 points**;
- late-game state diagnostics: for frozen leading/trailing buckets inside the final five minutes, fourth-down attempt rate and no-huddle/pace proxy must each be within **5.0 pp** where the empirical bucket has at least 200 qualifying possessions.

All required gates must pass. Sparse late-game buckets below the preregistered minimum are reported INSUFFICIENT_SAMPLE and block structural promotion rather than being silently dropped or pooled after results are seen.

### Attempt budget

The possession challenger has a hard budget of **8 calibration attempts**. Attempt 1 is the first fully executable preregistered challenger evaluated on the primary holdout. Any subsequent change to fitted parameters, state transitions, scoring probabilities, clock logic, fourth-down behavior, overtime behavior, feature set, tolerance, or acceptance calculation consumes one new attempt before reevaluation.

Bug fixes that can alter any simulated output also consume an attempt once attempt 1 has been evaluated. Pure tooling/reporting fixes proven byte-identical on the frozen simulation artifact do not.

Every attempt records code SHA, policy SHA, data/source hashes, RNG/version/seeds, parameter artifact, structural metrics and disposition. Attempts cannot be deleted or relabeled. If attempt 8 fails, the challenger is recorded FAILED_BUDGET_EXHAUSTED; the budget is not extended during this protocol.


## Amendment 1 — rule-regime parameterization (pre-output)

**Status:** preregistered amendment made before any possession-challenger simulation output or attempt-1 evaluation exists. This amends the protocol introduced at commit 343d761; it does not consume an attempt.

The challenger will **parameterize NFL rule regimes** rather than re-split the holdout. Rule parameters are exogenous inputs sourced from the applicable NFL rulebook and are never fitted to challenger holdout outcomes.

At minimum the rule-regime object must bind:
- season/effective-date identity and rulebook/source hash;
- kickoff format;
- kickoff/touchback placement rules that determine possession start state;
- onside-kick eligibility relevant to game state;
- regular-season overtime format, duration and possession-guarantee semantics;
- any later rule change that materially changes possession order/start state.

Historical games are simulated under the rule regime actually in force for that season. The primary structural holdout remains **2024-2025 regular seasons**, but it is now described as **held out from possession-challenger development**, not globally untouched by SportsEdge. Prior project exposure to game outcomes in those seasons is acknowledged and must be disclosed in the challenger evaluation report.

The development partition remains 2016-2019 and 2021-2023, with 2020 sensitivity-only. Development estimates behavior conditional on state; deterministic rulebook parameters provide the regime-specific transition constraints for 2024, 2025 and prospective 2026. Holdout outcomes may not be used to fit kickoff/touchback/OT parameters.

Because 2024 introduced the dynamic kickoff and 2025 modified kickoff/touchback rules and regular-season overtime, structural metrics sensitive to those rules must be reported by season/regime as well as pooled. A pooled pass cannot conceal a required regime-specific failure. Existing frozen tolerances apply to each sufficiently sampled required regime metric; preregistered minimum-sample rules continue to fail closed where applicable.

The eight-attempt challenger budget remains unchanged.


## Amendment 2 — new-regime behavior priors and noise-aware gates (pre-output)

**Status:** preregistered before any possession-challenger simulation output or attempt-1 evaluation. This amendment consumes zero attempts.

### Rule parameters versus behavioral parameters

Rulebook-defined transition constraints (spots, legal kickoff/onside structure, OT possession guarantees/duration) remain deterministic exogenous inputs. Behavior not specified by the rulebook is a separate parameter class and may not be inferred from the 2024-2025 challenger holdout.

For the 2024 and 2025 rule regimes, kickoff behavior and other regime-specific behavior inputs must be fixed before holdout evaluation from **published league-level summaries or other contemporaneous public aggregate reports** that do not expose the challenger's holdout target calculations. Each prior records source, publication date, applicable season, extraction rule and source hash. Examples include landing-zone/touchback/return mix and aggregate return-yard distribution. These values are disclosed as external empirical priors, not learned challenger coefficients.

If no admissible predeclared public aggregate exists for a required behavior parameter, use a documented conservative prior/range derived from pre-regime development data and mark the affected structural diagnostic PRIOR_UNCERTAIN. Do not fit the missing value on 2024 or 2025 outcomes after evaluation begins.

For 2026 rule changes with no completed-season behavioral sample, all regime-specific behavior inputs are **declared priors** with source/rationale and uncertainty bounds. They cannot create a validated 2026 structural claim until prospective data tests them. Sensitivity runs over the frozen prior bounds are required for any 2026 research readout materially affected by those parameters.

### Pooled hard gates plus noise-aware season diagnostics

Primary structural acceptance uses the already frozen **pooled 2024-2025 hard gates**. Season-specific 2024 and 2025 results are mandatory diagnostics and can block acceptance only under a preregistered sampling-error rule rather than the pooled fixed tolerance.

For a season-specific proportion metric with empirical rate p and n qualifying observations, define SE = sqrt(p*(1-p)/n). Its diagnostic acceptance band is the larger of:
1. the metric's existing frozen absolute tolerance; or
2. **1.96 * SE**.

For a season-specific mean metric, use the larger of the frozen absolute tolerance or **1.96 * empirical standard_error(mean)**. For quantiles, use a deterministic **2,000-replicate bootstrap** with a recorded seed derived from the policy SHA; the season diagnostic band is the larger of the frozen tolerance or the bootstrap 95% half-width.

A season diagnostic blocks only when its simulated-vs-empirical error exceeds that noise-aware band. Required minimum-sample rules still apply; insufficient samples remain INSUFFICIENT_SAMPLE and fail closed where the protocol marks the metric required.

The pooled gate remains the primary acceptance test; season diagnostics cannot rescue a pooled failure. Conversely, a pooled pass cannot override a season-specific failure outside its preregistered noise-aware band.

The eight-attempt budget remains unchanged.


## Amendment 3 — imported versus downstream structural evidence (pre-output)

**Status:** frozen before any possession-challenger simulation output or attempt-1 evaluation. Zero attempts consumed.

Every structural metric is classified before output. Classification cannot be changed after challenger results are observed.

### IMPORTED — consistency only, zero gate authority
The following are directly set or materially determined by external new-regime priors and therefore cannot contribute a structural PASS:
- kickoff landing-zone / placement mix;
- touchback rate;
- kickoff return versus touchback/out-of-play mix;
- kickoff return-yard distribution parameters supplied as priors;
- post-kickoff starting-field-position distribution to the extent directly induced by those priors.

These must be reported and checked for implementation consistency. A mismatch can FAIL/BLOCK the implementation, but a match contributes no positive evidence toward challenger acceptance.

### DOWNSTREAM — evidential gates
The following must emerge from the possession/game mechanics and retain full preregistered gate authority:
- possessions per team-game;
- opening-drive scoring rate;
- first-score probability conditional on opening-kickoff receiver;
- non-kickoff drive outcome mix: TD, FG, punt, turnover, turnover-on-downs, end-half/game;
- final margin mass at exactly 3, 7 and 10;
- mean and distribution of total points;
- late-game score/time-state fourth-down and pace behavior;
- any future sequence/player market diagnostic not directly supplied by an imported prior.

If a downstream metric later becomes directly parameterized by an external prior, that is a protocol change and cannot be reclassified inside the current attempt series.

### Pre-holdout development check

Before attempt 1 may inspect the 2024-2025 challenger holdout, the frozen challenger implementation must run on development seasons and record at minimum possessions per team-game and exact 3/7 margin mass (plus the other available structural diagnostics). This development check is for implementation/calibration readiness only and cannot create promotion evidence. Parameter changes made in response are permitted before attempt 1; once the implementation is sealed for holdout evaluation, the eight-attempt accounting begins.


## Development evaluator contract (pre-holdout)

Before the possession challenger is sealed for attempt 1, development evaluation must satisfy all of the following.

### Matchup-conditioned PIT inputs
Evaluate the actual development schedule, not league-average synthetic matchups. Each game receives only pregame point-in-time team-strength inputs computed from information available before that kickoff. Strength features and their source hashes/timestamps are persisted with the simulation manifest. Same-game/future outcomes and closing sportsbook prices cannot be strength inputs.

### Leave-one-season-out development validation
For each eligible development season S, fit/calibrate permitted behavioral parameters on the other development seasons and evaluate on S. Report every structural metric by fold and pooled across out-of-fold predictions. Parameter changes are judged on out-of-fold improvement; in-sample development fit cannot justify a change by itself.

### Monte Carlo precision
Every reported simulated metric includes path count, RNG/version/seed and Monte Carlo standard error or deterministic bootstrap interval as appropriate. Use at least **50,000 paths per development game** for the final pre-holdout baseline report. For proportion metrics, require MCSE <= **0.25 percentage points**; if not achieved, increase paths deterministically until it is. For means/quantiles, require the simulation 95% MC half-width <= **25% of that metric's frozen acceptance tolerance**. Failure to meet precision is MC_PRECISION_INSUFFICIENT, not a model failure/pass.

### Historical rule binding
The season rule-regime registry must cover the entire development window, not only 2024+. At minimum it must encode and source-hash the **2016 touchback-placement change** and the **2018 kickoff-formation/safety changes**, plus every later kickoff/OT rule change that materially affects possession start state, ordering or scoring mechanics. Rule parameters are selected by game date/season before simulation.


## Development evaluator scoring and compute contract

Development changes are judged on **pooled out-of-fold** performance first. Season-fold 3/7/10 mass is reported with empirical sampling uncertainty and is diagnostic rather than treated as a noise-free target.

For every held-out development game, persist the simulated integer-margin PMF and score the realized margin with preregistered negative log likelihood. To prevent undefined/infinite scores from finite Monte Carlo support, use additive smoothing fixed before evaluation: **Jeffreys 0.5 pseudocount per integer margin bin on support -80..80**, then renormalize. Report pooled out-of-fold mean NLL plus fold-level NLL. Structural changes must not be justified solely by improved key-number mass; their pooled OOF distribution score and the complete structural diagnostic set are recorded together.

The 50,000-path precision contract is unchanged.

### Compute implementation

Before the first full development sweep, the challenger must provide a vectorized/batched simulation path suitable for GitHub-hosted runners. Python object-per-possession loops may remain as a reference implementation for small invariant tests, but the evaluator uses NumPy array state over simulation paths and bounded game batches.

A deterministic equivalence test must compare the reference and vectorized implementations on frozen fixtures at the level of structural distributions/invariants. The fast path records batch size, NumPy/RNG version, seeds, path count and runtime. Runtime/resource failure is COMPUTE_INSUFFICIENT and cannot be resolved by silently lowering the frozen path count or precision requirement.


### Vectorized/reference distributional equivalence

Seeded path identity is **not** required between the object reference and vectorized implementations because random draws may be consumed in a different order. Before the vectorized evaluator is trusted, both implementations must be run on the same frozen synthetic matchup fixtures with **>=200,000 paths each** and independent recorded seeds.

Equivalence is distributional. Required comparisons and maximum absolute differences are:
- mean final margin: <= **0.15 points**;
- mean game total: <= **0.15 points**;
- mean possessions per team-game: <= **0.05 possessions**;
- exact margin mass at 3 and 7: <= **0.30 percentage points** each;
- each drive-outcome share (TD/FG/punt/turnover/downs/end-half-game when represented): <= **0.30 percentage points**;
- empirical margin and total CDFs: two-sample KS distance <= **0.01**.

All comparisons must pass. Failure is VECTOR_REFERENCE_MISMATCH and blocks development evaluation; it is an implementation defect, not a modeling result.

### Out-of-fold NLL benchmark

The possession challenger NLL must be interpreted against a frozen simple benchmark on the exact same leave-one-season-out games and the exact same PIT expected-margin input.

For each fold, fit **one residual standard deviation parameter** using only that fold's development-training seasons: residual = actual final margin minus PIT expected margin. The benchmark for each held-out game is a Normal distribution centered on its PIT expected margin with that training-only residual standard deviation, discretized to integer margins using half-point bin boundaries. Apply the same -80..80 support and Jeffreys 0.5 pseudocount/renormalization convention used for challenger scoring.

Report fold and pooled mean NLL for challenger and benchmark, plus paired per-game NLL difference. The challenger must have **lower pooled out-of-fold mean NLL** than the benchmark before its structural complexity can be claimed to add distributional predictive value. A failure does not consume a holdout attempt because this comparison occurs entirely in development.
