# OddsPapi v4 historical candidate admission — DRAFT build report

**Branch base main:** `d722da64cc984c4466bfb83457cc99d36f66c6e5`  
**Branch:** `feat/oddspapi-history-admission-harness-20261020`  
**Build status:** UNVERIFIED, no live credential, no account/browser access, no odds archival test, no independent admission decision.

## Contract and evidence

Official provider docs: https://oddspapi.io/us/docs/get-historical-odds
- v4 GET `/historical-odds` requires fixtureId + bookmakers and account API key in `apiKey` query; hierarchical response `fixtureId/bookmakers/markets/outcomes/players/` timestamped `createdAt` decimal `price` entries.
- Provider documentation states historical archive **since January 2026**, not 2025.
- Endpoint cooldown **5000ms**. This CLI makes a single request per invocation; it never loops/polls/retries or circumvents captcha.
- Existing SportsEdge credential name **`SPORTSEDGE_ODDSPAPI_KEY`** is reused from `scripts/archive_oddspapi_market_catalog.py`, not a second incompatible name.

## What the new harness actually admits

A structural `STRUCTURAL_CANDIDATE_UNVERIFIED`, **never a validated bookmaker market baseline**. It requires independent fixture anchor input with canonical event identity and date, versioned mapping with fixture-ID parity, separate source catalog SHA-256, exact one/two/three-way outcome ID map, and game-market player ID `0` only. Subject-specific player markets expressly refuse without player ID evidence. Numeric decimal prices must be finite >1; historical entries at/after scheduled start are excluded. The latest strictly prior snapshot per outcome is used, with a max 150-second outcome-timestamp span; timestamp ties with differing prices refuse. The output never claims actual-first-play binding, an executable DK market, a verified provider catalog, a two-way no-vig fair market, CLOSE, or `PLAY`. Independently pinned source evidence and documented market-baseline ruling are separate admission gates.

**Security**: API key stays in environment and request, never in stdout, exceptions or output file; exceptions are sanitized type/code only because provider requires API key in query URL. Raw response body and IP not persisted. CLI has hardcoded HTTPS provider host; only a single fixture request per execution. A synthetic `--response-json` mode allows offline validation without key. A nonzero BLOCKED result is produced when credential absent/denied.

## Artifacts (Git blob SHA-1)
* `scripts/oddspapi_history_admission.py`: `16e1c5b9a6df494b92a603f2ebc3253ed9da38c8`
* `tests/test_oddspapi_history_admission.py`: `db803321b46bab93e094b002dbb78a3d044bbe72`

## CLI contract (after key provision)

The operator must first supply **separately verified** local `anchor.json` with `fixtureId`, `scheduled_start_utc`, `canonical_event_id`, `fixture_anchor_sha256`, and `map.json` with version `ODDSPAPI_MARKET_ID_MAP_V1`, `fixtureId`, `bookmaker`, `market_id`, `canonical_market`, `player_id: "0"`, `market_catalog_sha256`, `selection_by_outcome_id`.

```bash
# No key is ever supplied on a command line.
export SPORTSEDGE_ODDSPAPI_KEY="<secret from account>"
python scripts/oddspapi_history_admission.py \
  --fixture-anchor-json anchor.json \
  --market-map-json map.json \
  --output-json candidate.json
```

Offline synthetic test path: add `--response-json fixture-envelope.json`. The output contains sanitized candidate readouts and provenance hashes only. No secrets are committed, and no API fetch is attempted by tests.

## Verification and remaining work

**Offline suite authored, NOT independently executed.** Host CI and Rocky must verify exact head, programmatic market-ID parsing against a real **non-secret** fixture response sample, session/credential handling, no query URL in exceptions, and all hostile tests. No 2025 backtest is possible through this archive: historical fixtures preceding 2026-01-01 are explicitly refused.

**Not proven:** key/account authority; provider fixtures/market IDs for the desired DK market; quote executable status and league fixture matching; actual first play; closed market timing; provider history completeness across fixtures; remaining historical paired-side coverage; market-baseline ruling's precise admissibility rule. No record or gate/registry mutation. Do not claim an admitted close or edge from this harness. As account captcha is owned by the user, the builder does not attempt bypass. The harness runs **upon explicit CLI invocation after a credential is supplied**; it does NOT automatically schedule itself when a secret appears.
