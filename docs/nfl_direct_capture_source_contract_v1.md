# NFL direct DraftKings confirmation source contract v1

`DRAFTKINGS_DIRECT_WEB_V1` is the primary authoritative transport for the NFL 2026 confirmation capture lane before the first successful capture creates `capture_lock.json`.

- Source: DraftKings' own public sportsbook sportscontent JSON for NFL full-game markets.
- Evidence clock: `observed_at_utc` is SportsEdge's HTTP-response receipt upper bound. It is not a DraftKings provider quote timestamp.
- Provider timestamps: `book_last_update` and `market_last_update` remain `null` for this source class. Receipt time must never be copied into either field.
- Raw fidelity: exact response bytes are persisted unchanged and bound by SHA256 before a capture row is accepted.
- Admission: requested full-game spreads/totals must remain two-sided. Missing sides, point mismatches, invalid identity, or otherwise unadmitted markets are never synthesized.
- Transport attempts: ordered attempt provenance is retained. V1 has exactly one declared host and no hidden fallback host.
- Executable identity: the adapter module SHA256 identifies the exact module bytes. Git SHA is repository provenance only.
- Fallback ranking: `DRAFTKINGS_DIRECT_WEB_V1` is primary. `DRAFTKINGS_ODDS_API_V1` may be attempted only after whole-source direct transport failure (HTTP/transport/malformed response), not to fill a valid direct board's missing/one-sided individual market.
- Cross-source merge: prohibited within a capture. One accepted capture uses one source class.
- Authority: this source contract grants no Model_P, promotion, Truth Gate, staking, or OFFICIAL authority by itself.
