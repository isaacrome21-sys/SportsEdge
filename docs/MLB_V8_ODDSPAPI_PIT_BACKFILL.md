# MLB V8 OddsPapi PIT Replay Backfill

## Purpose

Recover legitimate March 1-August 31, 2026 MLB point-in-time sportsbook evidence without inventing timestamps or relabelling open/close data as decision snapshots.

## Source contract

The frozen admission rules are in:

- `config/mlb_v8_oddspapi_evidence_contract.json`

The provider source is OddsPapi v4. Historical response bytes are archived exactly. Quote observation time is the provider's per-price `createdAt` timestamp, never the later retrieval time.

## Required GitHub secret

Create one repository Actions secret named:

`SPORTSEDGE_ODDSPAPI_KEY`

Do not commit the key to the repository or put it in an artifact. The collector passes it only as the provider `apiKey` query parameter and strips it from all stored metadata.

## Full replay workflow

Run:

`.github/workflows/mlb-v8-oddspapi-replay-backfill.yml`

Default inputs:

- books: `pinnacle,draftkings,fanduel`
- history calls per checkpoint: `120`
- maximum checkpoint batches: `30`

The workflow:

1. runs collector/PIT self-tests;
2. restores any prior progress from the `data` branch;
3. archives the market catalogue and its SHA-256 sidecar;
4. discovers finished MLB fixtures in provider-safe date windows;
5. downloads full historical odds with exact raw bytes and SHA-256 sidecars;
6. normalizes only genuine synchronized T-30 complementary pairs;
7. rejects deactivated, stale, one-sided, post-pitch, or timestamp-skewed quotes;
8. derives same-book/same-market paired pre-pitch closes when available;
9. checkpoints raw evidence, state, and normalized PIT evidence to the `data` branch after each batch.

## Files

- Collector: `scripts/backfill_mlb_v8_oddspapi.py`
- Market catalogue archive: `scripts/archive_oddspapi_market_catalog.py`
- PIT normalizer: `scripts/build_mlb_v8_oddspapi_pit.py`
- Frozen source rules: `config/mlb_v8_oddspapi_evidence_contract.json`

Durable evidence targets on `data`:

- `evidence/mlb_v8_replay_sources/ODDSPAPI_HISTORICAL/`
- `evidence/mlb_v8_replay_archive/oddspapi_pit/`
- `runtime/mlb-v8-replay-control/oddspapi_state.json`

## Acceptance rules

A T-30 pair is admitted only when both complementary sides are the latest provider state at or before the target, both are explicitly active, both prices are valid decimal odds, the oldest side is no more than six minutes old, and side timestamps differ by no more than 30 seconds.

The stricter frozen replay benchmark also records whether both sides are within 180 seconds of T-30. A later `active=false` record invalidates the earlier active quote; the normalizer never searches backward to resurrect it.

A close must use the same fixture, sportsbook, market ID/threshold, and player identity; both sides must be synchronized and strictly pre-first-pitch, and the close must be after the decision pair. No book switching is allowed for CLV.

## Governance

Completing PIT collection does not itself promote V8. The March-August chronological model replay, calibration/CLV/ROI gates, settlement semantics, production parity, and untouched September forward holdout remain separate required evidence layers.
