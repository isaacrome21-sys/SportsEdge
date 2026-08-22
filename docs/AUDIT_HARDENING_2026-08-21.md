# Audit and Hardening — 2026-08-21

Integration state: `INTEGRATION_UNRUN`.

This is repository inspection only. No pending PR was modified, no model math/gate changed, and no merge was performed.

## A1 — AutoRunReport construction

### Verified

On `main`, `sportsedge/auto_runner.py` defines the pre-#96 five-field `AutoRunReport` and constructs it positionally in `run_auto_mlb`.

On PR #96 head `701792a8c1fb17a2aa9e900632610c0163b13491`, `AutoRunReport` has eight fields after adding `run_status`, `card_status`, `coverage_slots`, and `market_surface_version`; `sportsedge/auto_runner.py` still constructs it positionally:

`AutoRunReport(slate_date_ct, current.isoformat(), status, card_status, results, coverage_slots, source_failures, surface_version)`

On the same #96 head, `sportsedge/auto_native_odds.py` reconstructs `AutoRunReport` with keyword arguments. That site is structurally safer.

Changed-file inspection for #101-#108 shows none of those PRs changes `auto_runner.py` or `auto_native_odds.py`, so the known constructor seam remains owned by #96 composition rather than a later pending branch.

### Required hardening, blocked by freeze

At Sept 1 composition time:

1. convert every `AutoRunReport` call to keywords;
2. make `AutoRunReport` keyword-only if compatible with the composed tree (`@dataclass(frozen=True, kw_only=True)`), so positional construction fails structurally;
3. add an AST-based contract test/lint that rejects positional calls to `AutoRunReport` anywhere in repository Python source;
4. run it against the exact composed tree, not reconstructed files.

No code change was made now because the hard freeze prohibits modifying #96 or opening a new feature PR.

## A2 — leakage audit

### Verified MLB guard

Both main and #96 `sportsedge/auto_runner.py` contain a fail-closed generic-feature ban for market-derived keys including `sportsbook_probability`, `implied_probability`, `market_probability`, `american_odds`, `decimal_odds`, `sportsbook_price`, and `dk_probability`. Generic feature resolution raises `GENERIC_FEATURE_MARKET_DATA_PROHIBITED` when those keys appear.

### Not fully verified

A repository-wide grep across every MLB residual layer and football M2 could not be truthfully completed from the connector because private-repository code search returned no indexed results. This is not a clean audit result.

Required Sept 1 real-clone command should grep at least: `sportsbook`, `line`, `total`, `implied`, `closing`, `odds`, `price`, `market_probability`, and known aliases through feature builders and M2 inputs, then manually classify every hit.

Status: `PARTIAL_INSPECTION`; no leakage finding is promoted from absence of search results.

## A3 — determinism audit

### Verified risks

- `sportsedge/auto_runner.py` reads `datetime.now(timezone.utc)` when `now` is not supplied. `generated_at_utc` reaches the report/artifact. Frozen-fixture execution must inject a fixed `now` or exclude execution metadata from the canonical decision payload.
- `sportsedge/auto_native_odds.py` likewise defaults to `datetime.now(timezone.utc)` and passes the resolved value into the runner.
- `scripts/archive_raw_game_odds.py` intentionally uses wall-clock time and timestamped status filenames; archive artifacts are operational evidence and are not the byte-identical model fixture target.

### Audit still required on exact tree

Search for unseeded `random`, `numpy.random`, default RNG constructors, wall-clock calls, unsorted `glob`/`iterdir`/`os.listdir`, set-to-list serialization, and JSON writes lacking canonical key ordering. The frozen fixture must run from different cwd/fresh processes/wall-clock contexts and compare the canonical decision payload byte-for-byte.

Status: `PARTIAL_INSPECTION`; full exact-tree determinism audit waits for a real clone/composed tree.

## A4 — import graph

### Verified archive isolation

`scripts/archive_raw_game_odds.py` imports only Python standard-library modules and `zoneinfo`; it imports nothing from `sportsedge/`. This preserves the archive lane's deliberate failure-domain isolation.

### Not fully verified

The connector inspection did not establish a complete import DAG for pricing/simulation/grading. Therefore no claim is made that pricing never imports simulation or grading never imports pricing across the whole repository.

Sept 1 should generate/import-scan the exact composed tree and fail on prohibited edges.

## Status matrix

| Item | PRESENT ON MAIN | RUNTIME EXECUTED | PRODUCING EVIDENCE |
|---|---|---|---|
| A1 constructor finding | No — #96 finding / research doc | No | No |
| A2 leakage audit | Partial guards exist on main | No full grep | No |
| A3 determinism audit | Risks identified in main code | No fixture execution | No |
| A4 archive isolation | Yes, archive source contract exists on main | Previously self-test capable; not executed in this audit | No new durable evidence |

No inspection result is integration evidence.
