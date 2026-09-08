# MLB raw-provider replay contract

Status: engineering contract only. This document does **not** claim authentic-provider evidence exists.

## Certified boundary

The MLB replay boundary begins at frozen **raw response bytes** from The Odds API. JSON parsing, provider-event binding, quote attestation, normalization, pairing, feature construction, model execution, and downstream evidence generation remain code under test.

A replay is invalid if parsed/reformatted JSON is used as the frozen input instead of the exact response bytes received from the provider.

## Storage boundary

SportsEdge is public. Paid-provider response bytes must not be committed to this repository.

The intended layout is:

- private evidence repository or other private checkout: raw response bytes only;
- public SportsEdge repository: replay code, manifest schema, SHA-256 hashes, tests, and non-provider metadata only.

The private checkout is supplied to CI as a filesystem root. The public manifest points to relative paths under that root and records the expected SHA-256 of every raw response.

## Manifest

Schema: `SPORTSEDGE_ODDS_API_RAW_REPLAY_V1`

Example shape (hashes are illustrative only):

```json
{
  "schema_version": "SPORTSEDGE_ODDS_API_RAW_REPLAY_V1",
  "responses": [
    {
      "label": "events",
      "path": "capture_001/events.json",
      "sha256": "<64 lowercase hex>"
    },
    {
      "label": "event:provider-event-id",
      "path": "capture_001/event_provider-event-id.json",
      "sha256": "<64 lowercase hex>"
    }
  ]
}
```

The manifest itself is also hashed at load time.

## Replay fail-closed rules

`FrozenOddsApiReplay` has no network client and no API-key path. It must fail on:

- missing manifest entry;
- missing raw response file;
- path traversal in a manifest entry;
- malformed or duplicate labels;
- invalid SHA-256 declarations;
- raw-byte SHA-256 mismatch;
- non-UTF-8 or malformed JSON after byte verification.

There is no cache-miss fallback to live acquisition. A miss is an evidence failure, not a fetch opportunity.

## CI wiring

When authentic raw bytes are available, a public-repo workflow may check out/pull the private evidence repository with a narrowly scoped credential, then execute replay against the private checkout. The workflow that performs the replay remains in SportsEdge, so its Actions usage is charged to SportsEdge; provider bytes remain outside the public repository.

Do not add a CI step that uploads the raw provider bytes as a public-repo artifact. Replay reports may publish only hashes, labels, code SHA, scope labels, and derived evidence that is permitted to be retained.

## Evidence state

As of this contract's introduction, SportsEdge has no retained authentic The Odds API MLB raw capture available to this branch. Therefore authentic MLB replay remains `BLOCKED_AUTHENTIC_RAW_BYTES_UNAVAILABLE`. Constructed provider-shaped fixtures are unit-test inputs only and cannot satisfy the authentic-provider acceptance gate.
