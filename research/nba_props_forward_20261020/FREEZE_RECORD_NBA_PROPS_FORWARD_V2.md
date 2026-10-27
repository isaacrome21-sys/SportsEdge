# FREEZE RECORD — NBA Player Props Forward Test V2 (Source Amendment)

**Document frozen:** `PREREG_NBA_PROPS_FORWARD_V2`
(`research/nba_props_forward_20261020/PREREG_NBA_PROPS_FORWARD_V2.md`)
**Freeze act:** owner's freeze, executed 2026-10-26 (America/Chicago) /
2026-10-27 (UTC). Freeze timestamp (asset retrieval, §4.1):
2026-10-27T01:37:13Z. Basis head: `6be7a394525f7558be7ec51cb8b80d0fc226bfed`
(branch `feat/nba-props-v2-evaluator-20261026`, PR #2757).
Everything under this test remains PAPER / 0u; no verdict creates a
PLAY and no staking authority is conferred.

## Status flips and pin re-strike (§12, condition 1)

- The preregistration header status flipped FINAL-CANDIDATE — NOT
  FROZEN → FROZEN, and the four V2 family config statuses flipped to
  FROZEN. No statistical term, gate, threshold, or evaluator logic
  changed.
- Flipping the document changed its sha256, so the pin was re-struck
  on the frozen bytes: **new pin
  `069cbf661e6ca733e9bda54ee3bc8a02163b20a5df7fcbbc89b10d9419a6aa02`**
  (old candidate pin
  `9a20c19193095ebb9f93b12fae3877465b81f91682427ba2770e60ebe5b3b944`).
  The new pin is recorded identically in all three records —
  `SPEC_HASHES.txt` (this directory), the evaluator constant
  `PREREG_SHA256_V2` in `sportsedge/forward_validation/nba_props.py`,
  and all four V2 family configs — and was verified by independent
  recompute of the frozen document's sha256. V1's pin and text are
  untouched; V2 counted rows, V1 rows, and research rows remain
  partitioned exactly as the evaluator implements (§10 separation).

## §4.1 freeze-time asset pin

Primary asset (prereg §2.1), downloaded fresh at freeze:

- **URL:** `https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_nba_player_boxscores/player_box_2027.csv`
- **Retrieved (UTC):** 2026-10-27T01:37:13Z
- **Byte size:** 605834
- **Release asset `updated_at`:** 2026-10-26T11:35:24Z
- **sha256 of raw bytes:** `7aa174d4a3a0c17f23c9fd868a4d7131b44418c5d39a059ea505ef3eaf5082d1`
  (identical to the digest published by the GitHub release API for
  this asset at retrieval time)
- **Raw bytes archived, unaltered, at:**
  `/home/hatch/workspace/goals/nba-readiness-and-backtest-harness/records/nba_props_forward_v2/player_box_2027_freeze_20261026.csv`
  (retrieval receipt beside it:
  `freeze_asset_receipt_20261026.json` in the same directory)

## Builder pin (§12, supporting recording)

- **Builder:** `slate_build.py`
- **Absolute path:** `/home/hatch/workspace/goals/nba-readiness-and-backtest-harness/hidden_files/nba_prop_store_20261026/slate_build.py`
- **Content sha256:** `c8f9d8235c5d97b73a6ca711e55789530bb6eaa92e9b978f0c8c4ac3372496b6`
  (verified against the file on disk at freeze time)

## First prospective counted slate (§12, condition 3)

**Named explicitly: the 2026-10-27 (America/Chicago) NBA slate —
the first slate priced after the freeze timestamp above.** Per
prereg §10, counting starts at zero at this freeze; rows from games
on or before the freeze date never count and no pre-freeze or
research slate is ever backfilled. Per §9, this slate contributes
counted rows only if its per-slate store build passes S1–S6 —
including the §7.3 positions-as-of-slate check (S3, §12 condition 4),
which is an event at that slate's build and cannot be satisfied in
advance; if it fails, the slate contributes zero counted rows and
the first counted slate is the first subsequent slate priced after
the freeze whose build passes S1–S6. Priced counted rows
additionally await the §7.4 sufficiency wall (≥10 prior played
games per player), so the first priced counted rows are expected
only around mid-November 2026 regardless of this freeze date.

## Records location (§12, supporting recording)

All V2 build manifests, store snapshots, proof artifacts, the
freeze-time asset archive, and priced-row records live in the goal
workspace's records area, concretely:

`/home/hatch/workspace/goals/nba-readiness-and-backtest-harness/records/nba_props_forward_v2/`

(per-slate archives are placed under this directory as their builds
occur, per §4.3, before that slate's rows are scored.)
