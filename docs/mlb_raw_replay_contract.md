# MLB raw-provider replay contract

Status: engineering contract only. This document does **not** claim authentic-provider evidence exists.

## Certified boundary

The MLB replay boundary begins at frozen **exact raw response bytes** from The Odds API. The bytes are verified before JSON parsing. Provider-event binding, quote attestation, canonical normalization, pairing, feature construction, model execution, and downstream evidence generation remain code under test.

A replay is invalid if parsed/reformatted JSON is used as the frozen input instead of the exact response bytes received from the provider.

## Storage boundary

SportsEdge is public. Paid-provider response bytes must not be committed to this repository.

The intended layout is:

- private evidence repository or other private checkout: exact raw response bytes only;
- public SportsEdge repository: replay/capture/verification code, manifest schema, SHA-256 hashes, and non-provider metadata only.

The private checkout is supplied to replay as a filesystem root. The public manifest points only to relative paths beneath that root and records the exact raw-byte SHA-256 and byte length for every response.

## Canonical public manifest

Schema: `THE_ODDS_API_RAW_FREEZE_MANIFEST_V1`

Each response is keyed by a SHA-256 of a canonical, secret-free request identity. The request identity contains method, provider host, path, and sorted non-secret query parameters. API-key/token query parameters are excluded before hashing and are never written to the manifest.

Example shape (hashes are illustrative only):

```json
{
  "schema_version": "THE_ODDS_API_RAW_FREEZE_MANIFEST_V1",
  "provider": "THE_ODDS_API",
  "sport": "mlb",
  "capture_id": "2026-09-08T180000Z",
  "captured_at_utc": "2026-09-08T18:00:00+00:00",
  "bookmakers": ["draftkings"],
  "response_count": 2,
  "responses": [
    {
      "request_sha256": "<64 lowercase hex>",
      "response_sha256": "<64 lowercase hex>",
      "private_path": "captures/2026-09-08T180000Z/responses/<request_sha>.bin",
      "byte_length": 1234
    }
  ],
  "manifest_sha256": "<64 lowercase hex>"
}
```

`manifest_sha256` is computed over the canonical manifest payload with the `manifest_sha256` field omitted.

## Capture path

`scripts/capture_mlb_odds_api_freeze.py` performs a live paid-provider capture. It writes response bodies only beneath `--private-root` and writes a metadata/hash manifest to `--manifest-out`.

Prefer supplying the provider key through `ODDS_API_KEY`; the command-line option exists for controlled use but should not be used in CI logs or shell history.

A capture is staged and promoted atomically only after the event list, featured game markets, and every discovered per-event player-prop response have been written. Duplicate canonical request identities fail closed.

## Replay path

`FrozenOddsReplayStore` verifies the manifest entry, private path containment, byte length, and exact response SHA-256 before returning bytes. Its `open()` method is urllib-compatible but has **no network implementation**.

`replay_mlb_game_quotes` and `replay_mlb_player_prop_quotes` inject only `FrozenOddsReplayStore.open` into the same production acquisition functions used by live The Odds API parsing. This intentionally exercises the production URL construction and provider parser while preventing any network fallback.

A replay hard-fails on:

- request not present in the public manifest;
- missing private response bytes;
- relative-path escape/traversal;
- malformed manifest identity;
- byte-length mismatch;
- exact raw-byte SHA-256 mismatch.

A frozen transport failure is an evidence failure, not a quote-level warning and not an opportunity to fetch live data.

## Verification

`scripts/verify_mlb_odds_api_freeze.py` verifies the public manifest hash plus every private raw response byte length and SHA-256. Its report contains hashes/metadata only and must never upload the raw provider bytes.

## CI wiring

When authentic raw bytes are available, a public-repo workflow may check out/pull the private evidence repository with a narrowly scoped credential, verify the manifest, and execute replay against that private checkout. The workflow remains in SportsEdge, while provider response bodies remain outside the public repository.

Do not upload raw provider bytes as a public-repository Actions artifact. Replay reports may publish only hashes, code SHA, replay scope/class labels, and derived evidence that is permitted to be retained.

## Evidence state

As of this contract's introduction, SportsEdge has no retained authentic The Odds API MLB raw capture available to this branch and the provider account previously returned `OUT_OF_USAGE_CREDITS`. Authentic-provider acceptance and authentic raw replay therefore remain `BLOCKED_AUTHENTIC_RAW_BYTES_UNAVAILABLE`.

Constructed provider-shaped fixtures are unit-test inputs only. They prove the fail-closed engineering contract; they do **not** satisfy authentic-provider acceptance and cannot promote any market, edge floor, eligibility flag, or Truth Gate status.
