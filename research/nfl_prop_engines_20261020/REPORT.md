# NFL prop engines v1 — build report (Oct 20, 2026)

Owner directive: any registered NFL prop family that still resolves
NO_ENGINE gets an engine built. Branch `feat/nfl-prop-engines-20261020`
on `b834101f9` (main `07b46d383` + CFB registration). Everything here is
RESEARCH; building an engine changed no family's registration state,
eligibility, or validation status — all 25 families remain
REGISTERED_RESEARCH_ONLY / NOT_VALIDATED, eligible=false,
promotable=false, and BLOCKED on the canonical coverage path.

## 1. Enumeration of the 25 registered families (authority per line)

Registry of record: `config/nfl_family_registry_v2.json` (PR #2371);
resolution of record: `sportsedge/canonical_coverage.py` (every
registered family resolves BLOCKED — NO_ENGINE except first_td, which
resolves NO_DATA).

**Already engined — not rebuilt (10):**

| Family | Engine of record |
|---|---|
| passing_yards, rushing_yards, receiving_yards, receptions | Frozen Part 2 evaluator on main (`research/nfl_props_part2_20261018/eval_nfl_props_calibration_v1.py`) |
| rush_yards | Alias of rushing_yards (same stat, same provider market) — the Part 2 engine |
| rush_attempts, attempts, completions, passing_tds | Part 2B freeze package (PR #2415, branch `feat/nfl-props-part2b-freeze-20261020`) |
| anytime_td | Engine v1 (branch `feat/nfl-atd-engine-v1-20261018`) |

**Scope-ruled — not built (1):** interceptions (QB thrown). Owner
ruling placed it OUT of the Part 2B scope; the pricer refuses it with
MARKET_OUT_OF_SCOPE_2B. Flagged here per instructions, not built.

**Not an engine gap — not built (1):** first_td. Canonical coverage
resolves it NO_DATA (NO_VERIFIED_FIRST_SCORING_ATTRIBUTION), not
NO_ENGINE: what is missing is verified first-scoring attribution data,
not a pricing construction. An assessment function already exists
(`nfl_anytime_td.assess_first_td`).

**Built in this package (10):** pass_plus_rush_yards,
rush_plus_rec_yards, targets, two_plus_td, fg_made, kicking_points,
xp_made, player_sacks, tackles_assists, player_interceptions.

**Not built — no honest construction exists on the sanctioned data
(3):** longest_completion, longest_rush, longest_reception. No per-game
longest-play outcome exists in any file of the sanctioned nflverse
snapshot: game logs carry sums and counts, never a maximum, so a
game-log engine would have to fabricate its outcome variable. An
in-repo play-by-play research engine (`nfl_longest_plays_empirical`,
matrix N25/N30/N31) exists, but it sits outside this build's data
mandate (PBP is not in the pinned snapshot) and remains
governance-unadmitted. Closing this gap is a data decision (admit a
PBP-derived per-game longest panel), not an engine decision.

## 2. Construction (one principled construction per family, scored once)

`sportsedge/nfl_prop_engines_v1.py` mirrors the frozen Part 2 evaluator
exactly in discipline: point-in-time nflverse game logs (regular season
only, games strictly before the priced week), role-gated qualification
(>= 3 prior games; role-mean threshold; QB-only where the market is a
QB market), the qualified league pool (earlier weeks of the season,
prior-season fallback), shrinkage `mu = (sum(prior) + K*pool_mean) /
(n + K)` with K = 3.0, one pooled CV per family from training ratios,
gamma CDF for yardage stats, Poisson / negative-binomial CDF for
counts. Only the stat, role gate, and CV differ per family:

| Family | Stat | Role gate | Dist |
|---|---|---|---|
| pass_plus_rush_yards | passing + rushing yards | attempts >= 20, QB only | gamma |
| rush_plus_rec_yards | rushing + receiving yards | carries + targets >= 8 | gamma |
| targets | targets | targets >= 4 | count |
| two_plus_td | rushing + receiving TDs | carries + targets >= 4 | count |
| fg_made | fg_made | fg_att >= 1.0 | count |
| xp_made | pat_made | pat_att >= 1.0 | count |
| kicking_points | 3*fg_made + pat_made | fg_att + pat_att >= 2.0 | count |
| player_sacks | def_sacks | total tackles >= 2.0 | count |
| tackles_assists | solo + assisted tackles | total tackles >= 3.0 | count |
| player_interceptions | def_interceptions | total tackles >= 3.0 | count |

Declared choices: two_plus_td's outcome is rushing + receiving TDs,
mirroring the anytime-TD v1 engine's rush/rec construction
(special-teams/fumble-return TDs excluded, as there; their measured
share was 0.23% of player-games). Tackles use total tackles (solo +
assists) as their own role gate — no snap/participation column exists
in the snapshot. Defensive sacks outcomes can be fractional (half
sacks); the count CDF and CRPS machinery handles them as recorded.

Loader rule that matters: a source file whose header lacks a family's
columns contributes NO rows to that family (absence of a column is
absence of data), never zero-filled rows. The ps files (2018-2024)
carry no kicking or defensive columns at all; those exist only in
sp_2025 (the newer nflverse stats-player format).

## 3. Calibration SCREEN results (USED 2020-2025 vintage — entry ticket, not validation)

Method identical to the Part 2 screen: CV from 2018-2019 training
ratios; scored qualified player-weeks (week >= 4) of 2020-2025; CRPS
vs B1 (player's own prior empirical CDF) and B2 (qualified league-pool
empirical CDF); verdict requires both block-bootstrap delta-CRPS 95%
CIs entirely below zero. Full machine-readable results:
`screen_results_v1.json` (data sha256 recorded there; games.csv
a484c6ae… matches the pinned vintage).

| Family | n | CV | CRPS cand / B1 / B2 | Δ vs B2 [95% CI] | Verdict |
|---|---|---|---|---|---|
| pass_plus_rush_yards | 2,360 | 0.3395 | 47.000 / 50.958 / 48.303 | −1.3032 [−2.0286, −0.6245] | **CALIBRATED_CANDIDATE** |
| rush_plus_rec_yards | 5,557 | 0.6155 | 22.061 / 23.708 / 23.998 | −1.9373 [−2.1398, −1.7148] | **CALIBRATED_CANDIDATE** |
| targets | 8,264 | 0.5154 | 1.674 / 1.787 / 1.865 | −0.1905 [−0.2060, −0.1749] | **CALIBRATED_CANDIDATE** |
| two_plus_td | 13,557 | 2.0900 | 0.266 / 0.284 / 0.267 | −0.0007 [−0.0022, +0.0007] | **DOES_NOT_BEAT_BASELINE** |

Sanity anchors: pass_plus_rush_yards scores exactly the Part 2
PASS_YDS population (n = 2,360 — the same QB gate) and targets exactly
the RECEPTIONS population (n = 8,264 — the same targets role gate).
Both combo-yardage verdicts agree with the Oct 18 sweep's N23/N32
CALIBRATED_CANDIDATE reads. two_plus_td beats the player's own-history
baseline (Δ vs B1 −0.0179 [−0.0219, −0.0140]) but only ties the league
pool — for the ≥2 TD tail, the shrunk-mean count model adds nothing
over the raw pool distribution. The engine is committed anyway, with
DOES_NOT_BEAT_BASELINE recorded on its registry entry: an honest
engine that fails its screen is a result, not a gap.

## 4. The six partial-vintage families — screen cannot run on the mandated vintage

fg_made, xp_made, kicking_points, player_sacks, tackles_assists,
player_interceptions: outcome columns exist only in sp_2025, so the
2020-2025 screen has nothing to score for 2020-2024. Verdict for each:
**SCREEN_NOT_RUNNABLE_SANCTIONED_VINTAGE** (recorded on the registry
entries). As supplementary evidence only, the screen script emits a
fenced 2025-only point-in-time diagnostic (CV from qualified rows of
weeks <= 8, scored weeks >= 9, same machinery), labeled
DIAGNOSTIC_PARTIAL_VINTAGE_2025_ONLY — it is not the family verdict:

| Family | diag n | CV | CRPS cand / B1 / B2 | Beats both (diagnostic only) |
|---|---|---|---|---|
| fg_made | 280 | 0.7624 | 0.701 / 0.756 / 0.699 | no (ties B2) |
| xp_made | 285 | 0.6314 | 0.779 / 0.830 / 0.802 | yes |
| kicking_points | 284 | 0.5528 | 2.146 / 2.282 / 2.185 | no (CI straddles 0 vs B2) |
| player_sacks | 3,942 | 3.3425 | 0.130 / 0.131 / 0.136 | no (ties B1, beats B2) |
| tackles_assists | 2,484 | 0.5582 | 1.444 / 1.498 / 1.645 | yes |
| player_interceptions | 2,484 | 5.0872 | 0.064 / 0.068 / 0.063 | no (loses to B2) |

The engines' CV constants for these six families are the diagnostic
CVs (provenance `SCREEN_2025_PARTIAL_VINTAGE` in the module and
registry), to be re-screened on the full vintage if a multi-season
sp-format panel is ever pinned.

## 5. Wiring

Registry: each built family gained an `engine` pointer and an
`engine_screen` record in `config/nfl_family_registry_v2.json`; no
governed field was touched (the v2 loader's invariants all pass, and a
test asserts canonical coverage still resolves all 25 families
BLOCKED).

Phone runner: `artifacts/run_it_full.py` was deliberately NOT touched
— two other builds are editing that file concurrently (CFB wiring,
NBA engines). Delivered instead: the pricing-entry module
(`price_nfl_prop` / `price_rows` in `sportsedge/nfl_prop_engines_v1.py`,
row contract mirroring the Part 2 forward runner: PRICED with
mu/cv/p_over/p_under or p_yes for the YES_ONLY family, NOT_QUALIFIED /
NOT_PRICED with named reasons). **Runner composition is the parent's
step.**

## 6. Tests

`tests/test_nfl_prop_engines_v1_20261020.py` — 21 tests, all passing:
per-family priced examples with sane bounds (parametrized over 9
families + the two_plus_td YES_ONLY contract), PIT traps (priced-week
and future outcomes excluded from both priors and pool; prior-season
pool fallback), sufficiency refusals (too few priors, role mean below
threshold, NOT_QB), unbuilt-family refusal (interceptions and
longest_rush raise), the loader column-presence rule on real
ps/sp-format files (no zero-fill), registry state/pointer assertions,
canonical-coverage-still-BLOCKED for all 25, and engine CVs matching
the screen results file.

Regression slice (registry v2, canonical run, family-gate wiring,
runtime enforcement, bypass probes, interception aliases, kicking and
longest empirical engines, per-game composite, milestone ingestion,
Part 2 suite): **310 passed**. A real-data smoke priced all ten
families on the pinned snapshot with sane probabilities (e.g. targets
mu 10.19 → P(over 8.5) 0.577; two_plus_td mu 0.90 → P(≥2) 0.193;
fg_made mu 2.44 → P(over 1.5) 0.646).

## 7. Surprises

- The 2018-2024 player-stats files carry NO kicking or defensive
  columns whatsoever; everything the registry lists as the "empirical
  kicking engine" era ran on play-by-play, not game logs. The
  defensive/kicking data gap is a format artifact of the pinned
  snapshot, closable by pinning sp-format files for more seasons.
- two_plus_td is the one clean screen failure: the model beats a
  player's own history but not the league pool — the ≥2 tail is
  pool-dominated at this construction's resolution.
- player_interceptions' diagnostic CV is 5.09 and its candidate loses
  to the pool baseline outright; the family may simply be near-noise
  at game-log resolution. Its engine is committed with that record.
