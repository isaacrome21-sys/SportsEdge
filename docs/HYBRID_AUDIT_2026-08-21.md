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

### Coverage limitation

The connected private-repo code-search index returned zero results even for the known symbol `AutoRunReport`. Therefore a claim that every construction site in all historical/unlisted branches was exhaustively found would be false. Exhaustive AST/grep coverage requires an authenticated clone or a functioning private-repo code index.

### Required Sept. 1 hardening

1. Convert every surviving `AutoRunReport(...)` construction site in the frozen composed tree to keyword arguments.
2. Add an AST/lint test that fails any `AutoRunReport` call containing positional arguments.
3. Run that guard against the exact composed tree, not reconstructed files.

Status:

- PRESENT ON MAIN: **YES — positional risk exists on main**
- RUNTIME EXECUTED: **NO — inspection only**
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

The frozen-fixture determinism target must therefore be the **canonical decision payload**, with all decision-relevant as-of times frozen. Operational envelope fields such as the execution timestamp/process metadata must either be frozen or kept outside the byte-identity comparison. A raw operational archive artifact containing a new run timestamp is not a valid byte-identical target.

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
- Push witness must contain the exact commit SHA.
- delayed witness is ineligible.
- valid clock ordering yields witnessed eligibility.

The aggregate zero-contribution test checks the paired sample denominator and both V5/V6 Brier/log-loss counts/sums plus calibration/paired-stat counts. This is deliberately standalone and does not alter V6.

Status:

- PRESENT ON MAIN: **NO — local research prototype only**
- RUNTIME EXECUTED: **LOCAL_RECONSTRUCTED_PASS — 6/6**
- PRODUCING EVIDENCE: **NO**

Production unblock: compose the integrity code onto the frozen Sept. 1 tree, run the adversarial tests branch-faithfully, and persist push witnesses at push time before any restored V6 observation is eligible.

---

## Integration status

No item in this audit upgrades the integration state. Component inspection and local reconstructed tests are not integration evidence.

`INTEGRATION_UNRUN`
