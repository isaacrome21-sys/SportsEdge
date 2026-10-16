# Dataset Manifest — NFL Totals LEVEL Model Evaluation

Written 2026-10-16, companion to
`PREREG_NFL_TOTALS_LEVEL_MODEL.md` (SHA-256 in `SPEC_HASHES.txt`).
This evaluation reuses the Stage 2 N1–N3 corpus and identity
verbatim so every number is comparable to the Stage 2 record.

## Corpus

| Field | Value |
|---|---|
| File | `games.csv` (local copy `~/workspace/tmp/bt_data/nfl_games.csv`) |
| SHA-256 | `a484c6ae884d03b11ab14f9fb3ed9ee8ca7168f3a22550e74f566532c4c6b284` |
| Source | nflverse — `nfldata` repository, `data/games.csv`, acquired 2026-10-15 (Stage 2) |
| Fields used | season, game_type, gameday, gametime, away_team, home_team, away_score, home_score |
| Fields present but NOT used | spread_line, total_line, moneyline/odds columns — never accessed by the evaluator |

**Not in the repository** (third-party data; nflverse attribution
terms apply). The evaluator verifies the SHA-256 at load and
refuses a mismatched file. The file is a living dataset; the
recorded hash is from the 2026-10-15 acquisition, and the
evaluator's verification binds this run to those exact bytes.

## Frozen-prior model identity

| Field | Value |
|---|---|
| File | `artifacts/free_models.py` (this branch's checkout of main `0f96676f`) |
| Git blob | `253b0c6d91840c906941216be117f2acc1497a57` |
| Note | Byte-identical to the Stage 2 pin (main `83e0c396a`); the evaluator verifies the blob at load |

## Published per-game audit (split for transport)

The evaluator's single audit CSV (2,127 rows) exceeds the push
transport's per-call limit, so it is published in five sequential
parts, `audit_nfl_totals_level_model_part1.csv` … `part5.csv`,
each repeating the header. Concatenating the parts' data rows in
order reproduces the whole file, whose SHA-256 is
`f0153a9c8280aabdf744a60cfbce5ae8e4d66adf1d3f018a9bf23161200bbd10`.

## Stage 2 reference values (reproduction precondition, prereg §1)

Paired subset (n = 1,887), from
`mlb_market_legs_20261014/results_n1_n3_nfl_calibration.json`
(on `research/mlb-market-legs-20261014`):

- Frozen prior mean total CRPS: 7.8225
- B2 climatology mean total CRPS: 7.7126
- Paired Δ (frozen − B2): +0.1099, 95% CI [+0.0283, +0.1987]
- Population: 2,127 scored REG games 2018–2025; 240
  climatology-ineligible.
