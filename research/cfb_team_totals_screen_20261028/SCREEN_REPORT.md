# CFB_TEAM_TOTAL_POSSESSION_V1 — historical design screen

## §0. Status and verdict

- Status: `DESIGN_SCREEN_RUN_ONCE` — historical design evidence only.
  Nothing here is frozen, no clock runs, no validation claim is made,
  and the family stays BLOCKED at `sportsedge/registry_gate.py`.
- Engine under test: `CFB_TEAM_TOTAL_POSSESSION_V1`, specified in
  `research/cfb_activation_20261027/DESIGN_CFB_TEAM_TOTALS_V1.md`
  (draft PR #2846), screened against the fixed criteria of
  `research/cfb_activation_20261027/PREREG_CFB_TEAM_TOTALS_FORWARD_V1_DRAFT.md` §4.
- Run of record: 2026-10-28 (America/Chicago), against current main
  `ad90b1486bcb17167d4169d3b18d0798c4ff8dcb` (the task pin `6eedf825e`
  verified as an ancestor of this main). See §7 for a disclosure about
  a preliminary execution on a different input vintage.

**VERDICT: SCREEN_FAIL** — §4.3 legs 1, 2, and 3 fail; legs 4 and 5
hold. Per prereg §4.5 the construction is recorded **FAILED_SCREEN**
and retired. No constant, threshold, feature, or cohort change may be
re-run against these seasons under this document; any successor is a
new construction under a new document, designed on these seasons as
DESIGN data.

The labeling discipline of the source documents applies verbatim:
SDV/CFBD closes are untimestamped snapshots → DESIGN baseline only;
beating them is never "verified CLV" (nothing here beats them in any
case); any ROI framing would be under a flat −110 price that is a
labeled ASSUMPTION — this screen computes no ROI at all.

## §1. Screen results (prereg §4.4 reporting)

Cohort: FBS vs FBS, Week 5+, ≥3 qualifying prior games per team,
Illinois-college games excluded before scoring, identical team-game
rows for every arm. n = 3,172 team-game rows (1,586 games).

### Pooled (2023–2025)

| Statistic | Value | §4.3 criterion | Holds? |
| --- | ---: | --- | --- |
| Residual beta (pooled OLS, intercept) | **−0.0274** | ≥ +0.10 | **NO** |
| MAE(M) | 9.453 | — | — |
| MAE(B-MKT) | 8.708 | MAE(M) ≤ MAE(B-MKT) + 0.5 = 9.208 | **NO** |
| MAE(B1) | 10.506 | MAE(M) < MAE(B1) | yes |
| MAE(B2) | 10.463 | MAE(M) < MAE(B2) | yes |
| 80% PI coverage (NB) | 0.827 | within [0.72, 0.88] | yes |
| CRPS(M) (NB distribution) | 6.683 | reporting only | — |
| CRPS(B-MKT) / (B1) / (B2) = MAE (point forecasts) | 8.708 / 10.506 / 10.463 | reporting only | — |
| Fitted NB dispersion r (per fold) | 5.06 (2023), 4.87 (2024), 4.89 (2025) | fit on prior seasons only | — |

Reporting-only intervals (game-cluster bootstrap, 2,000 resamples,
seed 20261028; no §4.3 criterion uses an interval): ΔMAE(M − B-MKT)
= +0.745, 95% CI [+0.608, +0.884] — the model's MAE deficit vs the
market baseline is not a noise artifact. Beta 95% CI [−0.114, +0.061].

### Per season

| Season | Games | Rows | Beta | MAE(M) | MAE(B-MKT) | MAE(B1) | MAE(B2) | CRPS(M) | 80% coverage |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2023 | 512 | 1,024 | −0.0686 | 9.566 | 8.786 | 10.628 | 10.646 | 6.736 | 0.821 |
| 2024 | 532 | 1,064 | −0.0279 | 9.607 | 8.945 | 10.525 | 10.438 | 6.784 | 0.828 |
| 2025 | 542 | 1,084 | −0.0137 | 9.195 | 8.403 | 10.371 | 10.315 | 6.533 | 0.830 |

Beta > 0 in 0 of 3 seasons (§4.3 leg 2 requires ≥2). MAE(M) exceeds
the MAE(B-MKT) + 0.5 tolerance pooled and in every season.

### Reading of the failure (design evidence, not a retune brief)

The disagreement signal the design hypothesized — that the market's
joint spread/total split misprices individual teams relative to a
possession model — is absent in these seasons: when the construction
disagrees with the implied split, actual scoring moves slightly
*against* the construction (negative beta every season). The
construction does beat both naive walk-forward baselines on MAE,
which says the possession machinery carries real information — just
less than the market's published close already contains.

### QB-sensitivity stratum (§4.4; reporting only)

Rows whose recorded primary passer (PBP-derived; see §3, P2) differs
from the team's prior game: 847 rows (26.7% of the cohort). Stratum
beta −0.0568; stratum MAE(M) 9.588 vs MAE(B-MKT) 8.842. The unmodeled
QB-change factor is associated with worse construction accuracy, as
the design's up-front risk statement anticipated — measured here,
never used as a feature, never used to trim the cohort.

## §2. Exclusion accounting (converged-screen format)

Evaluation seasons 2023–2025 unless a row says otherwise.

| Step | Game count |
| --- | ---: |
| Published betting rows | 2,835 |
| Not scoreable (collector codes) | 54 (E1_PLACEHOLDER_DEFAULT_SOURCE 25, E2_NO_SPREAD_VALUE 29) |
| Scoreable published spread / total | 2,781 / 2,781 |
| FBS vs FBS completed results | 2,398 |
| Illinois-college games excluded (`ILLINOIS_COLLEGE_EXCLUDED`) | 103 |
| Before Week 5 (excluded) | 707 |
| Week 5+, machinery-eligible (≥3 priors both teams, PBP-covered) | 1,588 |
| Missing a scoreable close (§4.1 identical-rows) | 2 |
| **Cohort games** | **1,586** |
| **Cohort team-game rows (all arms, identical)** | **3,172** |

Note: the converged screen's published exclusion split (E1 3 / E2 36
/ E4 15) assigns the same 54 games to different codes — this runner
tests the placeholder-source rule first, as ordered in
`scripts/collect_cfb_sdv_closes.py`'s rule list; the not-scoreable
total (54) and the scoreable count (2,781) agree exactly. Only
`completed` schedule rows with both final scores enter at all (E5
discipline inherited from the collector); no cohort row is a
postponed/cancelled game (void by construction of the funnel).

## §3. Data provenance (honesty over completeness)

All inputs are FREE public release assets, re-pinned by sha256 at
screen build in `PINS.json` beside this report.

- **P1 — outcomes + closes.** SDV release assets
  `cfb_schedules_{season}.csv.gz` and `betting_{season}.csv.gz`
  (sportsdataverse/sportsdataverse-data), 2021–2025, read as
  published. Settlement (final team points incl. OT) from
  `cfb_schedules` joined on game_id, per design §2.4. Governing
  baseline: the SDV published close (design §3.1).
- **P2 — play-by-play.** cfbfastR play-by-play, 2021–2025. The
  2022–2025 files are the sportsdataverse-data mirror release
  `cfbfastR_cfb_pbp` assets (the cfbfastR-data release route returned
  404 throughout the re-pull window; see §7); the 2021 file is the
  cfbfastR-data git-tree asset `pbp/parquet/play_by_play_2021.parquet`
  (the tree carries no later seasons). Used for drives/tempo
  construction and the §4.4 QB stratum. **Scope filter:** the mirror
  files cover all divisions; plays were restricted to games with at
  least one FBS team (the cfbfastR package cut) before any derivation.
  **Substitution, recorded:** prereg §4.4 names CFBD player game
  stats for the recorded-starter stratum; the CFBD API key is absent
  from this environment (verified unset; the API answers 401
  unauthenticated — the same wall recorded in PR #2831), so the
  stratum's recorded passer is derived from the PBP itself (the
  passer credited on the team's first dropback of the game; a
  dropback is any play with a recorded passer, applied uniformly
  across the two PBP column dialects). The stratum is reporting-only;
  the substitution changes no criterion and no cohort row.
- **P3 — CFBD betting lines (cross-check extract, design §4).** Not
  pulled: CFBD key wall (above). The design's governing baseline is
  the SDV close in any case, and CFBD explicit team-total fields were
  therefore not cross-checked. Recorded as an unexercised cross-check,
  not silently dropped.
- **Sign convention (design §3.1 pin-time duty).** Recorded from
  `scripts/collect_cfb_sdv_closes.py` + `scripts/evaluate_cfb_sdv_closes.py`
  at this pin: the collector carries `home_team_spread` and the
  evaluator computes `d["mkt"] = -d.home_team_spread` against
  `actual_margin = home_points − away_points` — i.e.
  `home_team_spread` is the home team's line in bettor convention
  (negative when home is favored), and the expected home margin is
  `S_close = −home_team_spread`. Proven on data (2023 file):
  mean(actual margin + home_team_spread) = +0.62 ≈ 0 (the close is an
  unbiased margin predictor) while the opposite-sign reading gives
  −12.34. The identity `implied_home = (T + S_close)/2`,
  `implied_away = (T − S_close)/2` was verified arithmetically on
  sampled rows (`implied_home + implied_away = T`,
  `implied_home − implied_away = S_close`).

## §4. Implementer readings (recorded BEFORE the run)

The design fixes the construction's form, the shrinkage constant,
the cohort, and every criterion. Where it leaves a functional form
unspecified, the reading taken was recorded here before any outcome
statistic was computed; no reading was changed after the run.

- **R1 — pace blend.** `projected_drives(i,j)` = arithmetic mean of
  team i's shrunk offensive drives/game and team j's shrunk defensive
  drives-allowed/game (defensive tempo allowance operationalized on
  the same drives-per-game scale, R3).
- **R2 — points-per-drive matchup.** The §2.2 "finishing profile" is
  operationalized as observed points per drive (all team scoring /
  offensive drives): `ppd(i,j) = ppd_off(i) × ppd_def_allowed(j) /
  league_ppd`, all rates shrunk per §2.3. Rationale: the design names
  no regression form, coefficient set, or feature weights for a
  fitted profile model, and inventing one after seeing the data
  layout would break the fixed-before-data rule; the profile
  statistics of §2.2 (PPA, success, explosiveness, Eckel, red-zone)
  are diagnostics of that finishing rate, not a specified second
  model.
- **R3 — drive counting.** A drive is a distinct PBP drive identifier
  for the offense as published (`drive_id`; `drive.id` in the 2021
  dialect). No drive-type filtering is applied. Points per drive uses
  schedule final team points / offensive drives (defensive/special
  scoring stays in the team's points, as it does in the settlement).
- **R4 — qualifying prior games.** A team's prior game counts toward
  its rate stats and the ≥3 gate if it appears in the PBP with the
  team on either side, any opponent division; the evaluation game
  itself must be FBS vs FBS.
- **R5 — prior-season pool.** §2.3's pool for season Y = prior-season
  (Y−1) final rates carried at half weight, centered on the league
  mean: `pool = 0.5 × prior-season team rate + 0.5 × league walk-forward
  rate`, with the league walk-forward rate as fallback when a team has
  no prior-season record in the pinned data.
- **R6 — dispersion fit.** NB dispersion r fit by maximum likelihood
  on walk-forward predictions over training seasons only (seasons
  strictly before the evaluation season, machinery eligibility as in
  §5), one pooled constant per evaluation fold. Fitted: r = 5.06
  (2023 fold, fit on 2021–2022 predictions), 4.87 (2024), 4.89 (2025).
- **R7 — intervals and CRPS.** 80% PI = [NB ppf(0.10), NB ppf(0.90)]
  at the row's mean and fold dispersion, inclusive coverage. CRPS
  for M from the NB CDF; for the point-forecast baselines CRPS
  reduces to MAE and is reported as such.
- **R8 — week keying.** Features for a game use games from strictly
  earlier (season, week) — the prereg's "before its week" — with the
  schedule `week` field as published; same-week games never enter
  each other's priors.

## §5. Method, in brief

Walk-forward over 2021–2025: for each game, team rates are computed
from that team's games in strictly earlier weeks of the season,
shrunk `w = n/(n+3)` toward the §2.3 pool (R5); league means are
walk-forward over the same expanding window. Model mean = projected
drives × points per drive (R1/R2). All four arms score the identical
3,172 rows. The runner is `run_screen.py` beside this report; inputs
are hash-pinned (`PINS.json`); the machine-readable run record is
`screen_results.json` beside this report. One run on the pinned
inputs; no sweeps; the §2.3 constant (3), the §4.3 thresholds, and
the readings above were all fixed before the first outcome statistic
was computed.

## §6. What this verdict does and does not do

- The construction `CFB_TEAM_TOTAL_POSSESSION_V1` is recorded
  FAILED_SCREEN and retired, in the same failure record as CFB PM /
  AM / PRIOR_CURRENT_BLEND / CFB_CONVERGED_ANCHOR_V1. It is not
  revised, re-run, or resurrected by anything here.
- The forward test in prereg §§5–11 never takes effect: its first
  condition (SCREEN_PASS under §4) is not met. No freeze is requested,
  no clock starts, counted rows remain zero by construction.
- A team-total verdict says nothing about the retired sides/totals
  constructions and reopens nothing gated on G3 (prereg §0.2/design §5).
- Verification, if a future new construction ever earns it, accrues
  forward only under the owner's Oct 27, 2026 definition — this
  screen is DESIGN evidence about a failed construction, nothing more.

## §7. Execution disclosure (scratch loss + input vintage)

Transparency about how this run came to be, because it affects how
the numbers should be read:

1. A first execution of this screen was completed on the original
   cfbfastR-data release-asset PBP files. Its scratch directory
   (inputs, runner outputs, predictions) was then lost to an
   environment cleanup before the deliverable was assembled; only
   its headline summary survived in the operator's notes: n = 3,144
   rows / 1,572 games; pooled beta −0.0259; MAE(M) 10.322 vs
   MAE(B-MKT) 9.778; coverage 0.677; fitted dispersion r = 19.47;
   verdict SCREEN_FAIL (legs 1, 2, 3, 5 failing).
2. The lost inputs could not be re-pulled identically: the
   cfbfastR-data release-asset route returned 404 for the entire
   re-pull window (the git tree carries the PBP only through 2021).
   The run of record above therefore uses the closest same-lineage
   source — the sportsdataverse-data `cfbfastR_cfb_pbp` mirror
   release — hash-pinned in `PINS.json`, with the FBS scope filter of
   §3 P2. The SDV schedules/betting files re-pulled byte-size
   identical to the first pull.
3. The two executions agree on the verdict and on every material
   fact: beta negative pooled and in all three seasons; MAE(M) worse
   than MAE(B-MKT) beyond the +0.5 tolerance; MAE(M) better than both
   naive baselines. They differ on leg 5 (coverage in-band on the run
   of record, below band on the preliminary execution, because the
   mirror vintage's fitted dispersion is heavier) and on magnitudes
   (different PBP vintage → different drive derivations → different
   cohort by 14 games). The numbers are NOT pooled or averaged; the
   run of record is the screen of record, and the preliminary numbers
   are disclosed here so the record shows both.
4. Because the verdict is SCREEN_FAIL under both executions, no
   inference in §6 depends on which vintage is believed. Had the run
   of record passed where the preliminary execution failed, this
   report would have recorded the screen as NOT-EXECUTABLE/contested
   instead — that rule was fixed before the re-run.

## §8. Freeze-coverage and hygiene

- Files added by the delivering PR (all under
  `research/cfb_team_totals_screen_20261028/`): `SCREEN_REPORT.md`,
  `run_screen.py`, `screen_results.json`, `PINS.json`,
  `SPEC_HASHES.txt`. Every path was checked against
  `config/freeze_reconciliation_registry_v1.json` (11 bundles:
  coverage prefixes/paths + token paths) — **no path is governed**;
  no registry, config, or governed-surface file is touched.
- Ruff gate (E9,F821,F822,F823,F811) clean on `run_screen.py`;
  dependency manifests untouched (parity gate unaffected); the
  runner uses only pandas/numpy/scipy (+ pyarrow to read the pinned
  PBP assets), all already present in the environment.
- The PR is a DRAFT. It does not merge, freeze, register, or start
  anything.
