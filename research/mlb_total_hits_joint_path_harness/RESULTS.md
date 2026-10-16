# RESULTS — MLB Total Hits joint-path harness (PREREG V1), step 7 scoring

Executed 2026-10-16 under the frozen preregistration
`PREREG_MLB_TOTAL_HITS_JOINT_PATH_HARNESS_V1.md`. This run changes no
production code and no status: the readout module remains
`UNVALIDATED_RESEARCH`. A PASS here would only have made the markets
eligible to be *considered* for a validation status change after
independent review; the outcome below is not a PASS in any case.

## Verdicts (preregistration section 8, applied verbatim)

| Market | Verdict |
| --- | --- |
| GAME_TOTAL_HITS | **DOES_NOT_PASS** |
| TEAM_TOTAL_HITS | **DOES_NOT_PASS** |

Each market fails on two independent grounds, either of which is
sufficient:

1. **The executed fold (2025) fails every leg.** Against the best
   baseline the candidate's RPS delta is positive with the bootstrap 95%
   CI entirely above zero (the candidate is significantly *worse*), its
   typical-line ECE exceeds the best baseline by far more than the
   0.005 tolerance, and its typical-line log loss is worse.
2. **The pooled cell is not computable as frozen.** Fold 2024 cannot be
   scored (see "Fold 2024" below), and section 8 requires the legs
   pooled *and* in every fold, so PASS was unavailable regardless of the
   fold-2025 outcome.

## Frozen identities (asserted by the scorer at runtime before any simulation)

- Preregistration SHA-256:
  `9080d16804ed9188083747a78b70520268cd2880ca303955256c65154a62a51b` (verified
  from the freeze-branch checkout; matches the frozen value).
- Construction under test (composed head `6ec17c716`, merge `1a10b7ffd`):
  - readout `sportsedge/research/mlb_joint_total_hits.py` blob
    `029829688817cfca4f1362dc2bdbe806dbaab42c`
  - path source `sportsedge/dfs/mlb_joint_paths.py` blob
    `50e027bc0a5551b2de9096292cc1c460567d5b63`
  - fitter `sportsedge/dfs/mlb_joint_path_fitter.py` blob
    `64c0319df8a93eec3621eb7babf2e2f84aa209be`

## Dataset and manifest (preregistration section 6)

- Source: the section-6 archived StatsAPI caches only (box scores and
  play-by-play). The archive contains regular-season games from the
  2024 and 2025 seasons only (earliest official date 2024-03-20); no
  pre-2024 games exist in it. Extraction integrity: hits and PA totals
  reconcile against the box scores for every parsed game; run totals
  differ in 6 games (runs are not a harness input).
- Correction applied **before scoring**: the cached season schedules
  list 71 games twice (identical date and facts). Those games are now
  processed once per gamePk; the dataset and manifest were rebuilt and
  re-hashed before any scoring ran (commits `db38596d0` then
  `bb754741f` on this branch carry both manifest versions).
- Manifest: `dataset_manifest.json` (shipped split as
  `dataset_manifest.parts/`, reassembles byte-identically).
  Canonical-content hash (manifest_sha256):
  `095cc1d691969224fea4ad160cc1a0cc1cc9c461097cbbede81e3972696a47e8`;
  whole-file SHA-256:
  `cddeb848f76e0b47d4f987c39159219b6982023ec6a90db96f337f032a685d4a`.
  Every scored game's input rows are SHA-256 hashed in the manifest.
- Declared fit policy `MLB_TOTAL_HITS_HARNESS_FIT_V1` (frozen in the
  manifest before scoring): batter profiles require ≥ 25 strictly-prior
  PAs (starter or bullpen column by the opposing starter's identity);
  hook surface fit once per fold on the training window over pitch bins
  (55, 70, 85, 100, 200) × runs-allowed bins (1, 2, 3, 4, 20), minimum
  training cell 51 trials, policy floor 50; baserunning profile fit
  once per fold (≥ 100 opportunities); lineups are the official
  boxscore starting orders.

## Fold 2024 — NOT_SCOREABLE_AS_FROZEN

Fold 2024's frozen training window (all games strictly before
2024-01-01) is absent from the section-6 archive, so its typical lines,
its league-rate baseline, and every batter's prior history are undefined
at the fold boundary. No within-season substitute was used: that would
be a different, unfrozen harness. Recorded in the manifest.

## Fold 2025 — executed in full

- Training window: 2,430 archived R games before 2025-01-01. Scoring
  window: 2,430 R games in 2025. **Scored: 1,118 games**
  (2025-03-27 → 2025-09-28), above the frozen 500-game floor.
- Excluded 1,312, each recorded in the manifest: 1,298
  `PROFILE_MIN_PA_NOT_MET` (a starting-nine batter below the 25-PA
  floor — a property of the frozen fit policy meeting early-season and
  platoon lineups, verified not an indexing defect) and 14
  `PLAYER_ID_COLLISION` (a player appearing in both lineups of one
  game, which the locked construction refuses).
- Typical lines, computed from the training window only and recorded in
  the manifest before scoring: game 15.5 (training median 16.0), team
  7.5 (median 8.0) — the grid half-line nearest the median, ties to the
  lower line.
- Execution: 10,000 paths per game, per-game SHA-256-derived seeds,
  exactly as frozen. Per-game PMFs for the candidate and all four
  baselines: `pmf_rows.jsonl`, SHA-256
  `4a4bc34fe687b3573535c69f6be806f22cfd61806df5d1477954c4299d1aa96c`
  (1,118 rows; held in the run workspace, hashed here; the compact
  per-game metrics input below carries everything the tables need).
- Determinism: a fixed 15-game sample was re-simulated from the stored
  inputs; candidate PMFs, path-set IDs and readout hashes were
  bit-identical for all 15 (`determinism_check.py`).
- No sportsbook prices were used anywhere. Every rate and feature uses
  games strictly before the game's official date.

### Fold-2025 tables (MEAN_RPS; lower is better)

GAME_TOTAL_HITS (grid 0.5–20.5, n = 1,118 games):

| Scorer | MEAN_RPS |
| --- | --- |
| candidate | 2.326372 |
| naive_team_rate_poisson | 2.225478 |
| **league_constant_rate (best)** | **2.209232** |
| trailing_20_game_team_rate | 2.309666 |
| independence_convolution | 2.248417 |

- Δ (candidate − best) = **+0.117140**, bootstrap 95% CI
  **[+0.058118, +0.175806]** (cluster bootstrap over GAME_ID, 2,000
  replicates, seed 20261015) — pass requires CI high < 0: **FAIL**.
- Typical line 15.5 — ECE candidate 0.119540 vs best 0.023874
  (tolerance +0.005): **FAIL**. Log loss candidate 0.717721 vs best
  0.685272: **FAIL**.

TEAM_TOTAL_HITS (grid 0.5–12.5, n = 2,236 team rows in 1,118 games):

| Scorer | MEAN_RPS |
| --- | --- |
| candidate | 1.739528 |
| naive_team_rate_poisson | 1.702001 |
| **league_constant_rate (best)** | **1.695856** |
| trailing_20_game_team_rate | 1.759796 |
| independence_convolution | 1.710608 |

- Δ = **+0.043673**, 95% CI **[+0.019106, +0.069036]**: **FAIL**.
- Typical line 7.5 — ECE candidate 0.091657 vs best 0.015564: **FAIL**.
  Log loss candidate 0.703001 vs best 0.685549: **FAIL**.

Machine-readable tables: `results.json`. Per-game evidence:
`metrics_input.parts/` + `metrics_input.parts.json` (gzip + base64
parts; reassembled SHA-256 of the plain JSONL:
`f6b88d6ee64c992077e82d6f2cc828822602361f2011dfe6703ae43029e1b08c`).
`verify_results.py` recomputes every number above from that file alone;
it passes.

### Post-hoc diagnostic (not part of the verdict)

The candidate's typical-line calibration is poor in a specific
direction: its over-probabilities run hot (ECE 0.120 / 0.092 against
baselines' 0.024 / 0.016) and its simulated game means exceeded realized
totals in spot checks — under this fit policy the joint-path simulator
overstates hit production relative to a flat league-rate distribution.
Any successor construction would need its own preregistration; nothing
here was tuned after the fact.

## Execution notes

- The scoring run was interrupted twice by environment restarts and
  resumed from its per-game checkpoint both times; the scorer
  re-asserts the frozen identities and the manifest hash on every
  start, and the final row set equals the manifest's scored set
  exactly (1,118 unique game IDs, no extras).
- The dataset manifest was committed on this branch before scoring
  (`db38596d0`, corrected `bb754741f`); remote publication of those
  commits proceeded through the repository's file-push transport,
  which is confirmation-gated per batch.
