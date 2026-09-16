# NFL direct DraftKings confirmation source contract v1

`DRAFTKINGS_DIRECT_WEB_V1` is the primary authoritative transport for the NFL 2026 confirmation capture lane before the first successful capture creates `capture_lock.json`.

- Source: DraftKings' own public sportsbook sportscontent JSON for NFL full-game markets.
- Evidence clock: `observed_at_utc` is SportsEdge's HTTP-response receipt upper bound. It is not a DraftKings provider quote timestamp.
- Provider timestamps: `book_last_update` and `market_last_update` remain `null` for this source class. Receipt time must never be copied into either field.
- Raw fidelity: exact response bytes are persisted unchanged and bound by SHA256 before a capture row is accepted.
- Admission: requested full-game spreads/totals must remain exact two-sided markets. Missing sides, point mismatches, invalid identity, or otherwise unadmitted markets are never synthesized.
- Slate completeness: OPENER and due FINAL captures must match the contemporaneous nflverse schedule snapshot by exact kickoff-UTC multiplicity before the capture lock can be created. A valid-but-partial DraftKings board is a failed capture, not a smaller successful slate.
- Schedule provenance: every accepted row set records the nflverse snapshot SHA256 and the expected kickoff multiplicities used for admission.
- Transport attempts: ordered attempt provenance is retained. V1 has exactly one declared host and no hidden fallback host.
- Executable identity: `adapter_module_sha256` identifies the exact adapter module bytes executed. Git/GitHub SHA is repository provenance only. The locked capture config additionally binds the direct transport, normalization, schedule-guard, and this contract by Git blob identity.
- Fallback ranking: `DRAFTKINGS_DIRECT_WEB_V1` is primary. `DRAFTKINGS_ODDS_API_V1` may be attempted only after whole-source direct failure (HTTP/transport/malformed response/identity failure), not to fill a valid direct board's missing, one-sided, or schedule-incomplete individual markets.
- Cross-source merge: prohibited within a capture. One accepted capture uses one source class.
- Retry suppression: only a previously admissible FINAL row may suppress another attempt for that event; malformed or incomplete prior files cannot poison the remainder of the live window.
- Persistence: lock and capture JSON files are created from fully flushed temporary files. If the first row write raises after creating a new lock and no capture row exists, the new lock is rolled back. A sudden process/runner termination between separate filesystem creations remains non-transactional and must be treated as a fail-visible operational incident, never reconstructed as market evidence.
- Authority: this source contract grants no Model_P, promotion, Truth Gate, staking, deployment eligibility, or OFFICIAL authority by itself.
