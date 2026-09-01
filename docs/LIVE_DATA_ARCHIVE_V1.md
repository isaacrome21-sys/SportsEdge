# LIVE_DATA_ARCHIVE_V1

Status: **DESIGN FROZEN / COLLECTION NOT YET PROVEN**

LIVE_ENGINE_V1 cannot be trained or promoted from ordinary pregame archives. It needs event-level historical replay evidence where every game-state snapshot and every market quote is timestamped at the moment it was actually available.

## Required archive unit

Each immutable archive row is keyed by:

`event_id + snapshot_id + pit_cutoff + record_type + record_hash`

Allowed record types are `STATE`, `QUOTE`, `MODEL`, `DECISION`, and `SETTLEMENT`.

The archive is append-only. A later state never mutates an earlier state. Historical replay must reconstruct the exact information set that existed at a decision point.

## Minimum replay evidence

For each candidate decision timestamp, replay needs:

- sport/event identity
- exact game state and source timestamp
- exact LIVE_PIT_CUTOFF
- governed pregame prior/model version
- sport-adapter feature vector
- feature provenance/as-of timestamps
- paired live book quote and quote timestamp
- book/market/contract identity
- market suspension/inactive state when observed
- live Model_P/model version when one exists
- no-vig market probability, edge, EV, sizing decision
- eventual outcome and settlement semantics
- later reference/closing quote for CLV when available

## Independence and sampling

Snapshots inside the same game are correlated. The archive may contain thousands of snapshots, but promotion statistics must preserve `event_id` clusters and report both raw snapshot count and independent game-cluster count.

## Collection cadence

A high-frequency collector is required for training-quality live data. GitHub Actions scheduling is not a sufficient substitute for second-level or play-level capture. Actions can run smoke tests and manual acquisitions, but production collection needs an always-on/event-driven process or equivalent infrastructure that can persist state and quotes at their native update cadence.

Until that collector is operating and durable evidence exists, live predictive validation remains **UNRUN**, not failed and not passed.
