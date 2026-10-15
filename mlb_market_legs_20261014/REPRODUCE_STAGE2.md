# Reproduce — MLB market-leg lane, Stage 2

Companion to `REPORT_STAGE2.md` (same folder). Stage 1's note is
`REPRODUCE.md`. Everything Stage 2 ran is pinned to repo main
`83e0c396a4761ea3de80583be5e61e8ca2e07f9a`; each evaluator verifies
its spec's SHA-256 (record: `SPEC_HASHES_STAGE2.txt`, recorded
before scoring; M31 also verifies Amendment 1) and its dataset's
hash at load and refuses on mismatch.

| Item | Evaluator (repo-root `scripts/`) | Results (this folder) | Data |
|---|---|---|---|
| M6 + M3 | `eval_mlb_cal_legs.py` | `results_m6_team_totals.json`, `results_m3_alt_runline.json` | SBR corpus (manifest §1; not in repo — SHA-256 in the manifest) |
| M29 | `eval_mlb_pitcher_pitches_cal.py` | `results_m29_pitcher_pitches.json` | StatsAPI cache (manifest §2; not in repo — combined identity SHA-256 in the manifest; re-acquirable from public endpoints) |
| M31 | `eval_mlb_either_dependence.py` | `results_m31_either_dependence.json` | same cache as M29 |
| N1–N3 | `eval_nfl_calibration.py` | `results_n1_n3_nfl_calibration.json` | nflverse `games.csv` (manifest §3; public download, SHA-256 in the manifest) |

Conventions: chronological walk-forward everywhere; ISO-week
block bootstrap, 2,000 resamples, seed 20261015; determinism =
re-run reproduces the results JSON except `generated_at`
(verified per item as recorded in REPORT_STAGE2 §7). Audit CSVs
(one row per scored unit) were retained with the lane's local
records and are available on request; the results JSONs carry
every aggregate the verdicts rest on, and M31's carries its full
per-cell tables and hand-check record.
