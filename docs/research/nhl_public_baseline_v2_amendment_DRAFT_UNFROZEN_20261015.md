# NHL public-baseline validation — v2 AMENDMENT DRAFT (UNFROZEN)

Status: **DRAFT_UNFROZEN — NOT A FREEZE, NOT AUTHORIZATION TO SCORE.**
Authority: owner ruling on #2268 (2026-10-15, comment 6202521040).
Research only: model_p=false, truth_gate=false, promotion=false, staking=false,
official=false. A retrospective PASS remains `RESEARCH_ONLY` (no PLAY, no market
or PIT validation). Prospective 2026-27 capture under separate governance is
still required for any verified-edge claim.

## 0. Relationship to v1 (v1 stays intact)

- `config/research/nhl_public_baseline_validation_prereg_v1.json`,
  `..._protocol_v1.json` and freeze bundle
  `NHL_PUBLIC_BASELINE_VALIDATION_RESEARCH_FREEZE_V1` (freeze_sha `378a6386`)
  are **not edited, superseded or relabelled**. v2 is a separate versioned file
  (`..._prereg_v2_amendment.json`, to be created only at freeze time).
- v1 validation window is unchanged and keeps its label:
  2025-10-01T00:00Z ≤ start < 2026-05-01T00:00Z,
  `REUSED_RETROSPECTIVE_DEVELOPMENT_HOLDOUT_NOT_FORWARD_BETTING_EVIDENCE`.
- The v1 combined fit-and-score validator is never run as a side effect.
  v2 requires its own runner, written and reviewed after this freeze.

## 1. Bound candidate (to be pinned by full SHA at freeze)

- Code: `sportsedge/sports/nhl/public_baseline.py::NHLPublicBaselineArtifact`
  and `fit_public_baseline` at main commit **f113a3e851d5a7fc33675c49c506b40affc09467**
  (or the commit recorded in the freeze if main moves; must equal v1 behaviour).
- Frozen v1 parameters: `ridge=1.0`; training cutoff start < 2025-07-01T00:00Z;
  `allowed_game_types=(2,)`; target `log(regulation_goals+0.5)` → predicted
  regulation goal rate λ via `artifact.regulation_goal_rate(features)`;
  `min_team_games=10`; the 8 v1 features in v1 order.
- Unit of evaluation: one row per team per game (2 rows per game), as v1.

## 2. Data and identity manifest (collection GO, scoring HOLD)

- Source: official NHL web API, regular season (`gameType==2`), `gameState`
  OFF/FINAL, games dated 2023-10-01 .. 2026-04-30. Raw response bytes, SHA-256
  and actual retrieval timestamps preserved (collection of 2026-10-15).
- **Schema-drift finding (blocking for preparation, not for collection):** the
  current `/v1/gamecenter/{id}/boxscore` payload no longer contains
  `boxscore.linescore`; the v1 parser (`official_boxscore_source.py`) rejects it
  ("official boxscore object required"). Period linescores and team PP/SOG are
  present in `/v1/gamecenter/{id}/right-rail` (`linescore.byPeriod`,
  `teamGameStats`). v2 data preparation must use a **separately reviewed
  adapter** that maps boxscore+right-rail raw bytes into the v1
  `NHLOfficialCompletedGame` fields without changing any v1 field meaning.
  The adapter is reviewed and its hash frozen **before** any v2 scoring, and
  it may be built/tested on fit-window games only.
- Manifest to be frozen: game-ID list per window, counts, per-file SHA-256,
  dataset SHA-256, failure list with reasons, excluded-row counts by reason.

## 3. Comparators (fit on training window only; no validation outcomes)

- **B0 — league home/away regulation-goal climatology.**
  λ_home = mean regulation goals of home teams over training rows;
  λ_away = same for away teams. Constant for every validation row.
- **B1 — team scoring/allowing baseline, shrunk.**
  For team T with n_T training games: GF_T, GA_T = training-window mean
  regulation goals for/against (home and away pooled).
  Shrunk: GF*_T = (n_T·GF_T + m·L)/(n_T + m), GA*_T = (n_T·GA_T + m·L)/(n_T + m),
  with L = league mean regulation goals per team-game (training) and **m = 20**.
  λ(T vs O, side s) = λ_s^B0 · (GF*_T / L) · (GA*_O / L).
  Teams with n_T < 10 training games use GF*_T = GA*_T = L.
- **Sequential updating: NONE** for candidate or baselines. All three use
  training-window fits only and are frozen at the cutoff. (Equal treatment;
  avoids any within-holdout outcome use.)
- The candidate's own features are pregame by construction (v1 chronology
  tests); they are computed from completed games before each target puck drop.

## 4. Primary metric and pass rule

- Per row i: NLL_i(model) = λ_i − y_i·log λ_i + log(y_i!), y_i = regulation goals.
- Paired difference per game g: D_g(X) = Σ_{rows in g} [NLL(candidate) − NLL(X)],
  for X ∈ {B0, B1}. Missing candidate or baseline row ⇒ game dropped from
  **all** comparisons (identical heldout rows); dropped count reported.
- Uncertainty: **clustered bootstrap by calendar game-day (US/Eastern date)**,
  resampling days with replacement; **B = 10,000**, **seed = 20261015**,
  percentile method. Both teams of a game and all games of a day stay together.
- **PASS (retrospective research skill only)** iff ALL hold:
  1. mean D(B0) < 0 and mean D(B1) < 0;
  2. one-sided upper 97.5% bootstrap bound of mean D(X) < 0 for X=B0 and X=B1;
  3. MAE noninferiority: MAE(candidate) − MAE(X) ≤ **+0.02 goals** for both X;
  4. RMSE: RMSE(candidate) − RMSE(X) ≤ **+0.02 goals** for both X;
  5. validation sample floor: **≥ 1,000 games (2,000 team rows)** after exclusions.
- Otherwise **FAIL** — recorded as binding negative evidence; no retuning,
  re-featuring or re-windowing on this holdout.
- Multiplicity: two primary comparisons; each at one-sided 2.5%, both required
  (intersection–union test; no further correction needed).

## 5. Diagnostics (reported, not part of PASS)

- Calibration: mean predicted vs actual by λ decile; Poisson PIT histogram
  (randomized), 10 bins; coverage of central 80% Poisson intervals.
- Home/away split of all metrics; per-month mean D.
- Counts: discovered, collected, parse failures, excluded (game type, non-final,
  missing linescore, < min_team_games), dropped for missing paired rows.

## 6. Exclusions (predeclared)

- gameType ≠ 2; gameState not OFF/FINAL; incomplete regulation linescore
  (fewer than three REG periods); teams with < 10 prior games (v1 rule); any
  record failing the reviewed adapter. All excluded counts published.

## 7. Freeze checklist (before any v2 scoring)

1. Owner/independent review of this text; numeric thresholds above confirmed
   or edited **without** viewing any validation-window statistic.
2. Reviewed adapter merged; its hash and the dataset manifest hash recorded.
3. Immutable v2 JSON with status `FROZEN_BEFORE_EVALUATION`, full SHA-256 of
   its bytes, source commit, and a new freeze-registry entry (separate bundle).
4. v2 runner reviewed; it must read validation outcomes only after (1)–(3).

## 8. Explicit non-claims

No NHL game has been scored. No validation-window statistic was computed or
viewed while drafting. This draft creates no authority.
