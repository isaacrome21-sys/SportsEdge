# CFB_TEAM_TOTAL_EPA_PROFILE_V2 — historical design screen

## §0. Status and verdict

- Status: `DESIGN_SCREEN_RUN_ONCE` — historical design evidence only.
  Nothing here is frozen, no clock runs, no validation claim is made,
  and the family stays BLOCKED at `sportsedge/registry_gate.py`.
- Engine under test: `CFB_TEAM_TOTAL_EPA_PROFILE_V2`, specified in
  `research/successor_designs_20261028/DESIGN_CFB_TEAM_TOTAL_EPA_PROFILE_V2.md`
  (merged in PR #2872), screened against the fixed criteria of
  `research/cfb_activation_20261027/PREREG_CFB_TEAM_TOTALS_FORWARD_V1_DRAFT.md`
  §4.3, carried **verbatim** by the design's §5 — no leg softer.
- Run of record: 2026-10-28 (America/Chicago), against main
  `956f28a30` (the PR #2872 merge). See §7 for the execution
  disclosure (an interrupted first execution and a recovery execution
  with byte-identical predictions).

**VERDICT: SCREEN_FAIL** — §4.3 legs 1, 2, and 3 fail; legs 4 and 5
hold. Per prereg §4.5 the construction is recorded **FAILED_SCREEN**
and retired. Per the design's §6 pre-committed stop rule, the CFB
team-total family is recorded **NO_VIABLE_CONSTRUCTION on current
admissible inputs** — the possession line (v1) and the profile line
(v2) are both exhausted; the family reopens only on a genuinely new
input class (a point-in-time designation record per G3's re-audit
triggers, or an admitted explicit team-total line archive), never on
a third estimator over the same inputs. No constant, threshold,
feature, or cohort change may be re-run against these seasons under
this document.

The labeling discipline of the source documents applies verbatim:
SDV/CFBD closes are untimestamped snapshots → DESIGN baseline only;
beating them is never "verified CLV" (nothing here beats them in any
case); any ROI framing would be under a flat −110 price that is a
labeled ASSUMPTION — this screen computes no ROI at all.

## §1. Screen results (prereg §4.4 reporting)

Cohort: FBS vs FBS, Week 5+, ≥3 qualifying prior games per team,
Illinois-college games excluded before scoring, identical team-game
rows for every arm. n = 3,172 team-game rows (1,586 games) — the
**identical cohort** scored by the v1 screen (PR #2861): the
cohort-identity gate (§3) reproduced its funnel exactly, and the
baseline arms reproduce v1's published MAEs to the last printed
digit (B-MKT 8.708070617906683 and B1 10.505465710029076 are
bit-identical; B2 differs at the 14th decimal, a summation-order
artifact).

### Pooled (2023–2025)

| Statistic | Value | §4.3 criterion | Holds? |
| --- | ---: | --- | --- |
| Residual beta (pooled OLS, intercept) | **−0.0086** | ≥ +0.10 | **NO** |
| MAE(M) | 9.836 | — | — |
| MAE(B-MKT) | 8.708 | MAE(M) ≤ MAE(B-MKT) + 0.5 = 9.208 | **NO** |
| MAE(B1) | 10.505 | MAE(M) < MAE(B1) | yes |
| MAE(B2) | 10.463 | MAE(M) < MAE(B2) | yes |
| 80% PI coverage (NB) | 0.837 | within [0.72, 0.88] | yes |
| CRPS(M) (NB distribution) | 6.946 | reporting only | — |
| CRPS(B-MKT) / (B1) / (B2) = MAE (point forecasts) | 8.708 / 10.505 / 10.463 | reporting only | — |
| Fitted NB dispersion r (per fold) | 4.57 (2023), 4.42 (2024), 4.48 (2025) | fit out-of-season only (V2-R6) | — |

Reporting-only intervals (game-cluster bootstrap, 2,000 resamples,
seed 20261028; no §4.3 criterion uses an interval): ΔMAE(M − B-MKT)
= +1.128, 95% CI [+0.947, +1.296] — the model's MAE deficit vs the
market baseline is not a noise artifact, and is *larger* than v1's
(+0.745). Beta 95% CI [−0.076, +0.060] — the interval excludes the
+0.10 the leg required.

### Per season

| Season | Games | Rows | Beta | MAE(M) | MAE(B-MKT) | MAE(B1) | MAE(B2) | CRPS(M) | 80% coverage |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2023 | 512 | 1,024 | −0.0812 | 9.942 | 8.786 | 10.628 | 10.646 | 7.019 | 0.837 |
| 2024 | 532 | 1,064 | +0.0380 | 9.929 | 8.945 | 10.525 | 10.438 | 7.002 | 0.838 |
| 2025 | 542 | 1,084 | −0.0023 | 9.644 | 8.403 | 10.371 | 10.315 | 6.820 | 0.836 |

Beta > 0 in 1 of 3 seasons (§4.3 leg 2 requires ≥2). MAE(M) exceeds
the MAE(B-MKT) + 0.5 tolerance pooled and in every season.

### Reading of the failure (design evidence, not a retune brief)

The estimator the v1 design named and never fit has now been fit,
and it does not rescue the claim. Pooled beta improved from v1's
−0.0274 to −0.0086 — still negative, with an interval that excludes
the required +0.10 — while pooled MAE *worsened* from v1's 9.453 to
9.836 against the identical split on identical rows. The design's
§6.1 prior is what the data returned: the implied split already
contains what public play-level efficiency knows, and a
cross-sectional fit of that efficiency to per-drive scoring adds
variance faster than signal. The design's §6.2 fit-form risk is
visible in the fitted maps themselves (§1.1): the EPA-differential
and success-differential coefficients flip sign by the 2025 fold.

### §1.1 Fitted maps (reporting; design §5 requires the continuity coefficient per fold)

Ridge per fold (V2-R1: features standardized on the training fold,
λ = 1.0, intercept unpenalized; target = realized points per drive;
n = machinery training rows from seasons strictly before the fold).
Coefficients on the raw feature scale:

| Feature | 2023 fold (n=2,328) | 2024 fold (n=3,560) | 2025 fold (n=4,798) |
| --- | ---: | ---: | ---: |
| Intercept (train ppd mean) | 2.195 | 2.173 | 2.172 |
| EPA differential | +0.328 | +0.234 | −0.191 |
| Success differential | −0.696 | −0.535 | +0.162 |
| Explosiveness differential | −0.912 | −0.588 | −0.592 |
| Eckel differential | +0.937 | +0.537 | +0.233 |
| RZ trip rate (matchup) | +5.301 | +5.490 | +5.649 |
| RZ TD differential | −0.022 | −0.067 | −0.112 |
| Projected drives | −0.016 | −0.009 | +0.035 |
| **Continuity × EPA differential** | **−0.014** | **+0.481** | **+0.729** |

The continuity term's fitted coefficient — the number the design
requires reported per fold — is **not stable**: ≈ 0 in the 2023
fold, positive and growing in 2024–2025. The design's own arithmetic
(§3.3) capped the term's possible pooled-beta contribution at
≈ +0.015 even if it worked perfectly; measured across folds it does
not present as a reliable effect, and the pooled construction fails
with or without it. The ppd floor of V2-R8 never bound (0 of 3,172
rows); the continuity pool-value fallback never fired in the scored
cohort (0 rows — every cohort row's two prior passers were recorded).

### §1.2 Strata (reporting only — never a criterion, never a cohort trim)

**QB-sensitivity stratum (prereg §4.4).** Rows whose recorded primary
passer (PBP-derived; v1 §3 P2) differs from the team's prior game:
**847 rows (26.7% of the cohort — the identical stratum rows as
v1's)**. Stratum beta **+0.0734**; stratum MAE(M) 9.903 vs
MAE(B-MKT) 8.842. (v1's construction scored −0.0568 beta on this
stratum; v2's fitted map disagrees with the split more profitably
here but still loses the stratum on MAE by over a point.)

**Continuity-zero stratum (successor reporting, design §5).** Rows
with continuity = 0 (the team's two most recent prior games were
started by different passers): 790 rows. Beta +0.1998; MAE(M) 9.551
vs MAE(B-MKT) 8.887. Reported because the design requires the term
measured, not asserted — and recorded here with its limit stated
plainly: this is a *subset* of a failed pooled test, selected by a
state the construction itself carries; it is not a pass, not a
near-miss, and under prereg §4.5 discipline it authorizes nothing.
The pooled legs govern, and they fail.

## §2. Exclusion accounting (converged-screen format)

Evaluation seasons 2023–2025 unless a row says otherwise. Every step
reproduces PR #2861's published funnel exactly.

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

Training universe (not scored; V2-R5): machinery team-game rows by
season — 2021: 1,116; 2022: 1,212; 2023: 1,232; 2024: 1,238; 2025:
1,258. Fold training sets: 2,328 (2023 fold), 3,560 (2024), 4,798
(2025). Dispersion (V2-R6) out-of-season prediction rows per fold:
1,212 / 2,444 / 3,682.

## §3. Data provenance (honesty over completeness)

All inputs are FREE public release assets, re-pinned by sha256 at
screen build in `PINS.json` beside this report. **All 15 files are
byte-identical to PR #2861's pins** (sha256 verified one by one
before the run; the mirror PBP *can* reproduce #2861's cohort, so
the design §7 falsification condition does not fire).

- **P1 — outcomes + closes.** SDV release assets
  `cfb_schedules_{season}.csv.gz` and `betting_{season}.csv.gz`
  (sportsdataverse/sportsdataverse-data), 2021–2025, read as
  published. Settlement (final team points incl. OT) from
  `cfb_schedules` joined on game_id, per design §2.4. Governing
  baseline: the SDV published close (design §3.1).
- **P2 — play-by-play.** cfbfastR play-by-play, 2021–2025. The
  2022–2025 files are the sportsdataverse-data mirror release
  `cfbfastR_cfb_pbp` assets; the 2021 file is the cfbfastR-data
  git-tree asset `pbp/parquet/play_by_play_2021.parquet`. **Scope
  filter:** plays restricted to games with at least one FBS team
  before any derivation (the cfbfastR package cut, as #2861 §3 P2).
  **Substitution, recorded (as in v1):** prereg §4.4 names CFBD
  player game stats for the recorded-starter stratum; the CFBD API
  key is absent from this environment (the API answers 401
  unauthenticated — the wall recorded in PRs #2831/#2861), so the
  recorded passer is derived from the PBP itself (the passer credited
  on the team's first dropback of the game; a dropback is any play
  with a recorded passer, applied uniformly across the two PBP
  column dialects). The stratum is reporting-only; the substitution
  changes no criterion and no cohort row.
- **P3 — CFBD betting lines (cross-check extract, design §4).** Not
  pulled: CFBD key wall (above). The design's governing baseline is
  the SDV close in any case, and CFBD explicit team-total fields
  were therefore not cross-checked. Recorded as an unexercised
  cross-check, not silently dropped (v1 §3 P3, carried).
- **Sign convention (design §3.1 pin-time duty).** Recorded from
  `scripts/collect_cfb_sdv_closes.py` + `scripts/evaluate_cfb_sdv_closes.py`:
  the collector carries `home_team_spread` and the evaluator computes
  `d["mkt"] = -d.home_team_spread` against
  `actual_margin = home_points − away_points` — i.e.
  `home_team_spread` is the home team's line in bettor convention
  (negative when home is favored), and the expected home margin is
  `S_close = −home_team_spread`. Proven on the scored rows at this
  pin: over the 1,586 cohort games, mean(actual margin +
  home_team_spread) = **+0.59 ≈ 0** (the close is an unbiased margin
  predictor under this reading) while the opposite-sign reading
  gives +6.44; the identity `implied_home = (T + S_close)/2`,
  `implied_away = (T − S_close)/2` holds **exactly** (max deviation
  0.0) on all 1,586 games. Strongest corroboration: MAE(B-MKT) and
  MAE(B1) on this run reproduce #2861's published values
  bit-for-bit (§1).
- **Dialect facts (pinned bytes).** The files' EPA column is named
  `EPA` (the design's `ep` field as the bytes name it). Success is
  one computed rule in both dialects (V2-R3); the mirror's shipped
  `success` column agrees with the rule on 99.48% of scrimmage
  plays. The 2021 file's down/distance/yards live in `start.down` /
  `start.distance` / `statYardage`, yards-to-goal in
  `start.yardsToEndzone`. See V2-R9 for the 2021 team-identity
  normalization.

## §4. Implementer readings (recorded BEFORE the run)

The design fixes the construction's form, feature list, cohort, and
every criterion. Where it delegates a constant or leaves a
functional form unspecified, the reading taken was recorded in the
runner's docstring **before any outcome statistic was computed**
(committed at `21034f3`, the pre-run commit containing the runner,
tests, and pins) and was not changed after the run. Summary:

- **V2-R1 — ridge penalty.** λ = 1.0 per standardized feature
  (features standardized on the training fold; intercept
  unpenalized); one value, fixed by this screen spec per design
  §3.2's delegation, not swept.
- **V2-R2 — profile rate discipline.** Per-game rates averaged over
  qualifying prior games, shrunk `w = n/(n+3)` toward
  0.5 × prior-season team rate + 0.5 × walk-forward league rate
  (v1 §2.3/R5 verbatim, per stat).
- **V2-R3 — play/drive derivations.** Scrimmage = pass/rush flag;
  EPA from the pinned `EPA` column; success = the cfbfastR
  50/70/100 rule computed uniformly in both dialects; drive = the
  published drive identifier (v1 R3); Eckel = a play starting at
  yards-to-goal ≤ 40; red-zone trip ≤ 20; red-zone TD = trip whose
  drive result is a possessing-team touchdown; drive points for
  points-per-Eckel (not an argument of g) mapped from drive result
  at the mirror's published `drive_pts` modes.
- **V2-R4 — matchup forms.** Differentials of shrunk rates;
  RZ trip matchup in the v1 R2 product form; projected drives =
  v1 R1 verbatim. g's arguments are exactly design §3.2's list plus
  the §3.3 interaction; the remaining §3.1 profile components (EPA
  split, points per Eckel, plays per drive) are computed on every
  team-game row as profile record and are not arguments of g.
- **V2-R5 — training universe.** Machinery team-games from seasons
  strictly before the fold (the v1 predict universe), as v1's
  dispersion fit used; the Illinois/FBS/Week-5/close filters define
  the scored cohort exactly as in v1.
- **V2-R6 — dispersion.** Out-of-season predictions only: per fold,
  maps fit on seasons < Y predict each training season Y ≥ 2022;
  the pooled predictions feed v1's bounded NB MLE verbatim.
- **V2-R7 — continuity state.** Within-season passer sequence (the
  v1 §4.4 sequence); pool-value fallback chain (walk-forward league
  rate → prior-season league rate → 0.5), flagged per row. Never
  fired in the scored cohort.
- **V2-R8 — fitted ppd floor.** Predictions floored at 0.0. Never
  bound (0 of 3,172 rows).
- **V2-R9 — 2021 team identity.** The pinned 2021 file keys
  `pos_team` by ESPN team ID; v1's name matching silently produced
  **zero** 2021 team-games under it (its dispersion fit rows
  decompose as 2022-only for the 2023 fold — 1,212 is exactly the
  2022 machinery count, reproduced by this build before the
  repair). This runner also matches `pos_team` against the pinned
  schedules' `home_id` / `away_id` and stores the schedule's
  canonical name for ID-matched rows. Proven on the pinned bytes
  before the run: the file covers 840 schedule games; in 839 the
  pos_team IDs are exactly a subset of {home_id, away_id}; one game
  carries a stray ID whose rows match neither side and are dropped,
  as any unmatched row is. The repair restores the design §4
  training reach to 2021 (1,116 machinery rows) and makes V2-R6
  executable as declared; it changes no criterion and no evaluation
  row — 2023–2025 features never read 2021 rows (in-season history
  plus the prior season's pool only) — and the cohort gate
  re-verified identity with the repair in place (§2).

## §5. Method, in brief

For every game 2021–2025, per-team §3.1 profile rates are built from
PBP plays strictly before the game's week (R8 keying), shrunk per
V2-R2. For each evaluation fold, the §3.2 ridge map is fit once on
training-season machinery team-games (target: realized points per
drive) and predicts the fold's cohort rows; mean points = projected
drives (V2-R4) × fitted ppd. The NB dispersion is fit per fold on
out-of-season predictions inside the training window (V2-R6); 80%
intervals from the NB CDF (v1 R7). All four arms score the identical
3,172 rows. The runner is `run_screen.py` beside this report; inputs
are hash-pinned (`PINS.json`); the machine-readable run record is
`screen_results.json` beside this report; unit tests are
`test_scree
...[truncated 3144 chars]