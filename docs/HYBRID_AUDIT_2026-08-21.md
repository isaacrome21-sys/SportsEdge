# SportsEdge Hybrid Audit — 2026-08-21

Integration state: `INTEGRATION_UNRUN`.

This document records inspection and local-research results only. It is not integration evidence, promotion evidence, or a merge authorization.

## Evidence vocabulary

Every item reports three independent states:

- **PRESENT ON MAIN** — the referenced production code/document exists on `main` at a verified SHA.
- **RUNTIME EXECUTED** — the relevant logic actually ran. Source inspection is not execution.
- **PRODUCING EVIDENCE** — the runtime produced a verified durable artifact suitable for the relevant evidence lane.

`CONNECTOR_EXACT_INSPECTION` means a file/branch was read directly from the private GitHub repository through the connected GitHub interface. It is exact source inspection, but it is not an authenticated local clone and does not prove import/seam behavior.

`LOCAL_RECONSTRUCTED_PASS` means standalone logic was reconstructed in a temporary local workspace and executed there. It is useful unit evidence but explicitly not branch-faithful integration evidence.

---

## A1 — AutoRunReport construction audit

### Exact findings

On `main`:

- `sportsedge/auto_runner.py` blob `d317a6a2e4fdd75ee1192b66eb6ac6b6196f62a3` constructs `AutoRunReport(...)` positionally.
- `sportsedge/auto_native_odds.py` blob `82529db214a3a3b6263f336b4df36914aca3b485` constructs `AutoRunReport(...)` positionally.

On PR #96 (`sportsedge/stage0-coverage-health-v2`, head `701792a8c1fb17a2aa9e900632610c0163b13491`):

- `auto_native_odds.py` was converted to keyword construction.
- `auto_runner.py` still constructs the expanded report positionally after the schema gained `run_status`, `card_status`, `coverage_slots`, and `market_surface_version`.

PR changed-file inspection for #101-#108 confirms none of those PRs modifies `auto_runner.py` or `auto_native_odds.py`. Therefore those branches inherit constructor behavior from their bases; they do not independently repair this seam.

### Local guard, test-first

A standalone AST guard was written locally. Initial test collection failed because the guard module did not yet exist:

```text
ModuleNotFoundError: No module named 'autorunreport_lint_local'
1 error in 0.07s
```

After implementation:

```text
...                                                                      [100%]
3 passed in 0.02s
```

The guard rejects any `AutoRunReport(...)` call containing positional arguments and accepts keyword-only construction. The tests use reconstructed known call shapes, not an authenticated clone.

### Coverage limitation

The connected private-repo code-search index returned zero results even for the known symbol `AutoRunReport`. Therefore a claim that every construction site in all historical/unlisted branches was exhaustively found would be false. Exhaustive AST/grep coverage requires an authenticated clone or a functioning private-repo code index.

### Required Sept. 1 hardening

1. Convert every surviving `AutoRunReport(...)` construction site in the frozen composed tree to keyword arguments.
2. Install the AST/lint guard in that exact tree.
3. Run it against the exact composition, not reconstructed snippets.

Status:

- PRESENT ON MAIN: **YES — positional risk exists on main; guard itself is not on main**
- RUNTIME EXECUTED: **LOCAL_RECONSTRUCTED_PASS — guard 3/3; production tree not executed**
- PRODUCING EVIDENCE: **NO**

---

## A2 — leakage audit

### NFL M2

`main:sportsedge/sports/nfl/m2.py` blob `3fbb2292cfd440f5555603e4f219755d18d900f7` contains recursive market-blind assertions plus explicit banned aliases. The emitted feature vector is football-native: EPA, pressure, success/explosiveness, rest/travel, wind/roof, QB, priors, and positional matchup features. No sportsbook line, total, implied probability, closing price, or book field was observed entering the emitted M2 feature vector.

### CFB M2

`main:sportsedge/sports/cfb/m2.py` blob `f977c79853a14ad517b87a6c6145b46932113edf` also bans direct market keys and emits football-native features only. No current observed market leak was found.

**Hardening gap:** CFB's guard is weaker than NFL's. It rejects exact names such as `spread_line`, `total_line`, `closing_price`, and `implied_probability`, but it lacks the NFL alias/pattern layer for names such as `home_spread`, `market_total`, `opening_odds`, or `consensus_implied_prob`. This is a vulnerability in the guard, not evidence that a leak currently enters the emitted vector.

### MLB V7

- `v7_baseball_features.py` blob `e8c7d515b6ded4f845ba29d140cd6439d9de5448` recursively rejects listed sportsbook/market fields.
- `v7_feature_bundle.py` blob `ea35f1924238b6343f2c4adb55ba680fb2ec7e68` defines the final model vector explicitly; the paths are baseball/context inputs only.
- `v7_environment_context.py` blob `e4113f0768c5cca30c56944c917ddaa1d517f60d` contains park/weather/travel/umpire/catcher inputs, not market state.
- `v7_training.py` blob `8d9e014661d9331443f3031ab97c4074b00feb70` trains through the explicit model vector and preserves chronological training/calibration/holdout separation.

No current market-derived feature was observed in the emitted V7 model vector.

Status:

- PRESENT ON MAIN: **YES — guards and current feature paths exist**
- RUNTIME EXECUTED: **NO — connector-exact inspection, not a runtime grep/AST scan**
- PRODUCING EVIDENCE: **NO**

Unblock for exhaustive audit: authenticated clone + repository-wide AST/grep over the exact frozen SHA, including generated/config feature declarations.

---

## A3 — determinism audit

### Deterministic paths found

- `sportsedge/identity_rng.py` blob `2080cf18515fc70cfa78dc75c546cf130aa94bf0` derives stable RNG state from a validated build hash.
- `sportsedge/v7_distribution.py` blob `e8aadfd73d36f6fe6be1a5c41bbe320c787bd9d6` defaults to 50,000 simulations, fixed seed `7`, and a local `random.Random(seed)`.

### Concrete nondeterminism risk

`main:sportsedge/core/simulate/football.py` blob `921300b62e546c8c30664fbf7986025a7f78e3aa` defines `JointScoreSimulator(..., seed: int | None = None)` and passes that directly to `numpy.random.default_rng(seed)`. If callers omit the seed, NumPy seeds from nondeterministic entropy. Therefore byte-identical replay is not guaranteed by that class contract.

### Wall-clock / artifact boundary

- `auto_runner.py` defaults to `datetime.now(...)` when `now` is not injected.
- `scripts/archive_raw_game_odds.py` intentionally reads the wall clock and embeds run timestamps in status/raw paths.

The frozen-fixture determinism target must therefore be the **canonical decision payload**, with all decision-relevant as-of times frozen. Operational envelope fields such as execution timestamp/process metadata must either be frozen or kept outside the byte-identity comparison. A raw operational archive artifact containing a new run timestamp is not a valid byte-identical target.

### Exhaustiveness limitation

Private-repo code search was unavailable. A complete scan for every `random`, NumPy RNG, `datetime.now`, `time.time`, unsorted filesystem iteration, set iteration affecting serialization, and directory glob dependency requires an authenticated clone/AST scan.

Status:

- PRESENT ON MAIN: **YES — both deterministic helpers and the football seed risk exist**
- RUNTIME EXECUTED: **NO — inspection only**
- PRODUCING EVIDENCE: **NO**

---

## A4 — import-graph audit

### Archive isolation

`main:scripts/archive_raw_game_odds.py` is standalone standard-library code and imports nothing from `sportsedge/`. This satisfies the reliability-lane isolation contract by inspection.

### Requested layer checks

- `sportsedge/devig.py` blob `2e0515d1bf5595784920cd21dab3afe6bf20da69` does not import simulation.
- `sportsedge/funnel.py` blob `c458db0bb50f2df23aa99d5b6665af0d143f69cc` does not import pricing; it summarizes already-produced rows.

### Non-blocking layering smell

`devig.py` imports `american_to_decimal` from `truth_gate.py`. That is gate-utility reuse from the pricing layer, not the prohibited pricing->simulation coupling, but it is worth separating later so pricing primitives do not depend on a gate module.

Status:

- PRESENT ON MAIN: **YES**
- RUNTIME EXECUTED: **NO — import inspection only**
- PRODUCING EVIDENCE: **NO**

---

## C1/C2 — local V6 integrity prototype

A standalone local prototype was developed test-first because production integration is frozen.

Initial failing collection:

```text
ERROR collecting test_v6_integrity_local.py
ModuleNotFoundError: No module named 'v6_integrity_local'
1 error in 0.08s
```

After implementing the local integrity checker:

```text
...... [100%]
6 passed in 0.05s
```

Covered locally:

- `POST_FIRST_PITCH_PREDICTION_COMMIT` contributes zero to the promotion aggregate.
- `PREDICTION_COMMIT_UNRESOLVABLE` contributes zero.
- `FIRST_PITCH_PROOF_MISSING` contributes zero.
- generic witness must contain the exact commit SHA.
- delayed witness is ineligible.
- valid clock ordering yields witnessed eligibility.

The aggregate zero-contribution test checks the paired sample denominator and both V5/V6 Brier/log-loss counts/sums plus calibration/paired-stat counts. This is deliberately standalone and does not alter V6.

Status:

- PRESENT ON MAIN: **NO — local research prototype only**
- RUNTIME EXECUTED: **LOCAL_RECONSTRUCTED_PASS — 6/6**
- PRODUCING EVIDENCE: **NO**

Production unblock: compose the integrity code onto the frozen Sept. 1 tree, run the adversarial tests branch-faithfully, and persist a valid remote witness before any restored V6 observation is eligible.

---

## C3 — remote witness semantic verification

Official GitHub documentation exposed a critical distinction:

- Enterprise Cloud REST Events API `PushEvent` exposes event `created_at` and push payload `ref`, `head`, `before`, but the current documented payload does not expose `commits[]`.
- GitHub push **webhook** payloads do expose the pushed `commits` array.
- Repository webhook delivery metadata exposes `delivered_at` and the request payload.
- Events API timelines are capped (up to 300 events, only events from the preceding 30 days) and are explicitly not real-time.

Therefore the old combined assumption "REST PushEvent `created_at` + target SHA appears in that same payload" is not valid for arbitrary non-head commits. The V6 integrity spec was refined to require a versioned witness source that proves both remote time and exact commit membership, preferring a push-webhook delivery witness. Unverifiable membership remains fail-closed.

Status:

- PRESENT ON MAIN: **NO — refined integrity spec is docs-branch research only**
- RUNTIME EXECUTED: **NO — semantic/source verification, not production execution**
- PRODUCING EVIDENCE: **NO**

---

## D1 — Retrosheet feasibility

Official Retrosheet field documentation confirms starter/substitution identity, inning/outs/score state, pitcher/batter identity, pitch sequences/counts when known, and game metadata. It does **not** provide a complete structured starter-removal-cause field.

Research conclusion:

- `COMPLETED_PATH`: partial/inferential; actual path is observable, manager intent is not.
- `PITCH_COUNT_EXHAUSTION`: partial; pitch detail can be missing and pregame workload prior is external.
- `PERFORMANCE_HOOK`: inferential; surrounding performance state is observable, managerial motive is not.
- `TACTICAL_SUBSTITUTION`: inferential/low-confidence; substitution and matchup state are observable, motive is not.
- `INJURY_HEALTH`: mostly unclassifiable; no complete standardized player-injury exit field.
- `WEATHER_DELAY`: partial/sparse; suspension/delay comments exist, but weather cause must be explicit.
- `UNKNOWN`: fully available and required fallback.

Structured ejections are outside the seven-label taxonomy and therefore remain `UNKNOWN`; they must not be forced into performance/tactical categories.

Status:

- PRESENT ON MAIN: **NO — research doc only**
- RUNTIME EXECUTED: **NO — source-field audit only**
- PRODUCING EVIDENCE: **NO**

---

## D2/D3/D4 — local LABELRULES_V1 + coverage/version harness

### Test-first history

Initial collection before implementation:

```text
ModuleNotFoundError: No module named 'engine_b_labelrules_local'
1 error in 0.09s
```

The first implementation then produced a useful failure rather than being papered over:

```text
4 failed, 4 passed in 0.05s
```

The failures showed that the default synthetic workload prior was causing `PITCH_COUNT_EXHAUSTION` to absorb cases intended to exercise competing hazards. That exposed the otherwise ambiguous "Rule 2 / Rule 3" wording.

The research contract was made explicit: labels are numbered in listed order, so Rule 2 = `PITCH_COUNT_EXHAUSTION` and Rule 3 = `PERFORMANCE_HOOK`. Unresolved competing inferred hazards fail closed to `UNKNOWN`; no silent rule-order tie break is allowed.

Final local result:

```text
.........                                                                [100%]
9 passed in 0.03s
```

Covered:

- 75 pitches can classify differently under different **pregame workload priors**; no universal pitch threshold.
- Rule 2/Rule 3 near-tie -> `UNKNOWN`.
- a predeclared dominance margin can resolve Rule 2/Rule 3 where one evidence strength clearly dominates.
- unclassified injury does not inflate `PERFORMANCE_HOOK`.
- explicit weather delay receives its own label.
- large positive and negative score differentials do not by themselves become a monotone cause label.
- unresolved multi-hazard inferred cases -> `UNKNOWN`.
- labels are exhaustive/mutually exclusive in the harness.
- coverage audit reports unknown separately and frequencies sum to 1.
- frozen historical seasons are `[2021, 2022, 2023, 2024, 2025]`.

The version harness emits placeholders for `starter_class_version` and `workload_prior_version` because those models have not been fit; this prevents the local rule test from masquerading as a historical mechanism result.

Status:

- PRESENT ON MAIN: **NO — local research code only**
- RUNTIME EXECUTED: **LOCAL_RECONSTRUCTED_PASS — 9/9**
- PRODUCING EVIDENCE: **NO — no Retrosheet historical exits were classified**

Unblock for mechanism evidence: acquire/freeze 2021-2025 Retrosheet data, build ex-ante pregame workload priors/starter classes, execute the source extractor, report actual cause-label coverage, then validate distribution/threshold/mechanism out of time.

---

## Integration status

No item in this audit upgrades the integration state. Component inspection and local reconstructed tests are not integration evidence.

`INTEGRATION_UNRUN`
