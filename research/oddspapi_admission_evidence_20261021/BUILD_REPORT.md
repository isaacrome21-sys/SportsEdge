# Admission evidence-acquisition layer — DRAFT BUILD RECORD (2026-10-21 CT)

**Build branch:** `feat/oddspapi-admission-evidence-20261021`
**Base at creation:** `663fb022a290ea8e25816f5822e1ce5ba063fdf9` (origin/main; #2444 merge)
**Scope:** New additive modules and fixture-driven tests only. **No** modification to any existing file, **no** pinned config surface touched (`config/mlb_model_surface_v1.json` untouched — no placement conflict arose), **no** secrets read or handled, **no** live API calls in the build or its tests, **no** admission-state changes. No own-work verification claimed; independent verification is Rocky's separate pass.

## What this is

The admission RUN (Phase 1 step 6 of the finish plan) needs three pieces of evidence machinery that did not exist as code. This PR builds exactly those three, as evidence-packet tooling only. It runs no check and files no disposition: every output carries `admission: NOT_ADMITTED` / `verdict: NO_VERDICT`.

### 1. Frozen pull — `sportsedge/oddspapi_frozen_pull.py`

Given a frozen target list `{sport, event_id, date}`, fetches each target's `/v4/historical-odds` payload through an injected `fetch(path, params) -> (status, body)` callable and freezes the raw bytes content-addressed (`raw/<sha256>.json`) with manifest entries `{target, endpoint, bookmaker, retrieved_at, sha256, bytes}`. Request params mirror the merged #2436 pattern (`fixtureId=<event_id>&bookmakers=draftkings`); sport/date are freeze metadata recorded in the manifest. Fail-closed: any target failing (non-200, empty/non-bytes body, duplicate, malformed target) aborts the pull and **no manifest is written** — a partial freeze can never pose as a complete one. `verify_pull_dir` recomputes every entry against disk and refuses on hash/bytes mismatch or a missing raw file.

Credential handling: the module never sees a key. The live factory `connector_fetch()` mirrors the registered `custom.oddspapi` helper (`oddspapi_get.py`): `dynamic_credentials` places the connection surrogate in the `apiKey` query parameter and the real key is swapped in only on the approved request; redirects refused; the factory is lazy and is never invoked by tests.

### 2. R1 cohort assembly — `sportsedge/oddspapi_r1_cohort.py`

Assembles Check A candidate pairs from our own DraftKings capture records in the **exact input shape the merged #2446 instrument consumes** — the pair and quote key sets are #2446's own (`{sample_id, dk, oddspapi}`; DK quote `{canonical_event_id, market_id, bookmaker, side, line, captured_at_utc, american_price, source_sha256}`; the Papi side carries `decimal_price` instead of `american_price`, supplied later by the run). The integration is proven by test, not by assertion: assembled samples are fed through the real `evaluate_numeric_admission_dryrun` and return `A_UNPAIRED_SAMPLE` rows (the `oddspapi` side is `None` until the run joins a frozen pull), and `build_numeric_dryrun_envelope` emits exactly #2446's fixed four-key envelope, importing its `VERSION` constant so the two cannot drift.

Assembly conventions (choices of this layer, recorded here; #2446 treats both strings as opaque exact-match identities):
- `canonical_event_id = "<SPORT>:<game_date>:<AWAY>_AT_<HOME>"` — the `_AT_` separator exists because #2446's canonical-id pattern admits no `@`.
- `market_id = SPREAD | MONEYLINE | TOTAL | TEAM_TOTAL:<ABBR> | PROP_<STAT>:<PLAYER_SLUG>`.
- Each quote's `source_sha256` is the SHA-256 of the canonical JSON of the exact capture sub-object the quote was read from — every assembled row traces to a byte-stable slice of a committed capture file, and the cohort manifest hash binds all sample ids + source hashes.
- The same fixture legitimately appears in multiple captures (AM entry and PM close are distinct samples of one event); a duplicate fixture **within one capture file** refuses (`R1_DUPLICATE_EVENT_IN_CAPTURE`). Present-but-malformed market rows refuse with named codes (`R1_QUOTE_FIELD_MISSING:<field>`, `R1_PRICE_INVALID`, `R1_CAPTURED_AT_OFFSET_REQUIRED`, ...); absent markets are skipped and counted.

Real records were located and used (not fixtures): `~/workspace/sportsedge/dk_line_archive/nba/2026-10-20/1023_ct.json` (111,036 bytes) and `1722_ct.json` (100,799 bytes), the Oct 20 scheduled NBA captures (records branch `records/audit-artifacts-20261018`). Assembling both yields **2,352 candidate samples over 27 games** (SPREAD 54, MONEYLINE 54, TOTAL 54, TEAM_TOTAL 108, PROP_POINTS 592, PROP_REBOUNDS 576, PROP_ASSISTS 448, PROP_PRA 466), zero skipped markets, cohort manifest `a7ce7785fc547e9e...`. The committed test suite uses synthetic fixtures for determinism and additionally smoke-tests these real files when present (skipped where they are absent, e.g. hosted CI).

### 3. First-play anchors — `sportsedge/oddspapi_first_play_anchors.py`

A records module for independently sourced actual start/first-play times: `{event_id, actual_first_play_at, source_name, source_url_or_id, retrieved_at}`, exact key set enforced. Anchors are **inputs with provenance, never derived from any odds payload** — this module imports nothing from the pull or cohort code and reads no odds data, because a start time extracted from the source under test would certify itself. A lookup miss returns the explicit state `{"event_id": ..., "anchor_state": "NO_ANCHOR"}`; nothing is inferred from scheduled starts or neighboring games. `to_instrument_anchor` converts a record to #2446's `actual_first_play` shape, with `official_source_sha256` = SHA-256 of the canonical anchor record — a binding content hash of the provenance claim, **not** authentication of the source (the same caveat #2446 itself states). Carried into a close candidate with no anchor, the value is an explicit `None`, which #2446 scores as `D_INDEPENDENT_ACTUAL_FIRST_PLAY_NOT_SUPPLIED` (proven by test). Conflicting duplicate anchors for one event refuse; identical duplicates dedupe.

## Governance placement

Modules live in the governed `sportsedge/` package beside their siblings (`oddspapi_history_admission.py` #2436, `oddspapi_numeric_admission_ad.py` #2446), tests in `tests/`, this record under `research/`. Nothing imports the runner, pricing, or card paths; nothing in the repo imports these modules yet (the admission run is a separate later step). Stamps on every output: `NOT_ADMITTED` / `NO_VERDICT` with `eligible`/`play_authority` never asserted anywhere in the new code.

## Tests (author-run, this machine)

- `tests/test_oddspapi_admission_evidence.py` — **11 passed**: frozen-pull freeze + verify round-trip; tampered raw byte refused (`PULL_MANIFEST_SHA_MISMATCH`); HTTP failure writes no manifest; duplicate/malformed targets refused; cohort sample shape equals #2446's key sets exactly; malformed capture row and naive-timestamp row refused with named codes; assembled cohort + anchored close fed through the real #2446 instrument (A rows unpaired-fail, D row passes numerically, top-level `admission` still `NOT_ADMITTED`); anchor hit / explicit `NO_ANCHOR` miss; conflicting anchor refused; close candidate without anchor scores `D_INDEPENDENT_ACTUAL_FIRST_PLAY_NOT_SUPPLIED`; real Oct 20 captures assemble (2,352 samples, 27 games).
- Neighbors: `tests/test_oddspapi_numeric_admission_ad.py` + `tests/test_oddspapi_history_admission.py` + `tests/test_freeze_inventory.py` — **57 passed**.
- Repo collector self-test: `scripts/collect_mlb_the_odds_api_history.py --self-test` → `SELF_TEST_OK`, exit 0.

## Exact Git blob SHA-1s

- `sportsedge/oddspapi_frozen_pull.py` — `8c171b457406eeb0d6128ef18a03518e521f558c` (229 lines)
- `sportsedge/oddspapi_r1_cohort.py` — `2d5ee156cff89cf7cf27508cad8b1bab68a6e885` (307 lines)
- `sportsedge/oddspapi_first_play_anchors.py` — `8be9532bdea6aef83ddcdeb502825602ca4ede5a` (112 lines)
- `tests/test_oddspapi_admission_evidence.py` — `4226941e647be7cbcfcb3170da693cf2cb084905` (264 lines)

## What this does NOT do

No live pull was executed; no target list has been frozen by an owner ruling yet; no pairing of R1 samples to provider payloads has occurred; no anchor records have been collected. The admission RUN remains a separate, later step that consumes this layer — and even a complete run admits nothing by itself beyond the protocol's pre-set per-market bars.
