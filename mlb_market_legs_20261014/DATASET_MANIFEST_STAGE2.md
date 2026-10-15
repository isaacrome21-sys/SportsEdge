# Dataset Manifest — Stage 2 (M6, M3, M29, M31, N1–N3)

Written 2026-10-15, before any Stage 2 scoring. Companion to the
Stage 1 manifest (`DATASET_MANIFEST.md`, hash-locked at
`390519c5d66ddda96491d70ba25d1e2a1126e902b814b80b9127220031360317`),
which is **not** edited by this stage.

## Shared model pin

All Stage 2 evaluations pin main
`83e0c396a4761ea3de80583be5e61e8ca2e07f9a`. The two evaluand files
are blob-identical to the pins Stage 1 and Phase 2 scored:
`artifacts/free_models.py` =
`253b0c6d91840c906941216be117f2acc1497a57` (also at `2a713380c`
and `12999fc22`); `sportsedge/pitcher_joint_engine.py` =
`00cba6f664e313b53ab0084e6f3f471a9d85b566` (also at `12999fc22`).

## 1. SBR corpus (M6, M3) — reused from Stage 1

`mlb_odds_dataset.json`, SHA-256
`3f952fd0bfae9f4f2d17e66692cb936ce6e1a5f6b415318012090c85933b882b`.
Full provenance in the Stage 1 manifest. **Not in the repository.**
Stage 2 additionally consumes the Stage 1 published audit artifact
`audit_m2_runline.csv`, SHA-256
`b0b39ab2a92e2114ed4ecaa9b0823396fb28bbd917d248e8cf448b82967b39dc`
(on `research/mlb-market-legs-20261014`) — this one IS in the
repository, as a Stage 1 output.

## 2. StatsAPI cache (M29, M31)

| Field | Value |
|---|---|
| Location | `~/workspace/tmp/bt_data/statsapi_cache/` (local only) |
| Files | 6,175 JSON payloads (URL-keyed disk cache) |
| Combined identity | SHA-256 `87841854d03f8e65686503b1ee19c011d66604d6501bc9c96fee1b6d18cea55e` over the sorted `sha256sum` listing (per-file hash + filename, one per line) |
| Acquisition record | `~/workspace/tmp/bt_data/ACQUISITION_DONE.json`: gameLogs for 747 pitchers, seasons 2024 + 2025; schedule linescore months 2023-09 → 2025-09 (for the sibling F5 evaluation); completed 2026-10-14 with zero errors |
| Source | MLB StatsAPI (`https://statsapi.mlb.com/api/v1`), public endpoints, acquired by the backtest program's `acquire_statsapi.py` |

**Not in the repository** — it is a transport cache of public API
responses; any reproduction re-acquires from StatsAPI and rebuilds
the same population through the production collector's semantics
(the evaluators' parity checks bind the population to the
production source, not to this cache's bytes).

## 3. nflverse schedule corpus (N1–N3)

| Field | Value |
|---|---|
| File | `games.csv` (local copy `~/workspace/tmp/bt_data/nfl_games.csv`) |
| SHA-256 | `a484c6ae884d03b11ab14f9fb3ed9ee8ca7168f3a22550e74f566532c4c6b284` |
| Size | 2,184,486 bytes; 7,548 games |
| Source | nflverse — `nfldata` repository, `data/games.csv` (canonical raw URL `https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv`), downloaded 2026-10-15 |
| Fields used | season, game_type, gameday, gametime, away_team, home_team, away_score, home_score |
| Fields present but NOT used | spread_line, total_line, moneyline/odds columns (see SPEC_N1_N3 headnote: the market-leg classification is a property of the evidence standard) |

**Not in the repository** (third-party data; nflverse attribution
terms apply). The evaluator verifies the SHA-256 at load and
refuses a mismatched file: after acquiring the file from the source
above, `sha256sum games.csv` must print the hash in this table, or
the verdicts do not transfer. Note the file is a living dataset
(nflverse updates it in-season); the hash pins the exact bytes
these verdicts were computed on.
