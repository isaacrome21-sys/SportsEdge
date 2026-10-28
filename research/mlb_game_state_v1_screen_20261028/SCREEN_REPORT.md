# MLB_GAME_STATE_V1 — historical screen report

**Verdict: FAILED_SCREEN**

Design: `research/mlb_game_lines_successor_20261028/DESIGN.md` (PR #2887).
One configuration, the declared constants in `BUILD_RECORD.md`, folds
mirroring V1 (fit ≤2022→2023, ≤2023→2024, ≤2024→2025), 7,218 scored
games. No freeze, no forward rows, no validation claim — the design
reserves verification to the 2027 forward clock, and this screen does
not pass in any case. Per the standing law the family is recorded as
FAILED_SCREEN; no tuning follows from these results (any successor is a
new version with its own preregistered criteria).

## Per-criterion results (design §5.2 — ALL required)

| # | Criterion | Result |
|---|---|---|
| 1 | ML Brier AND log loss beat home base rate AND simple Elo, pooled AND every fold; totals MAE AND team-total MAE beat league-average baselines, pooled AND every fold | **FAIL** (pooled legs pass; two folds fail — below) |
| 2 | Beat the V1-shaped control on identical folds/data, pooled Brier | **FAIL** — full 0.2450 vs control 0.2437 (paired bootstrap Δ +0.00134, 95% CI [−0.00003, +0.00267]) |
| 3 | Calibration gate: no probability decile with n ≥ 200 off by > 7.5 pp | **PASS** — worst decile deviation 0.0547 (decile 1, n = 721) |
| 4 | Market-proxy leg (2025 fold): ML Brier beats the consensus close's Brier on the same games | **FAIL** — full 0.2440 vs proxy 0.2416 on 2,092 matched games (log loss 0.6807 vs 0.6758) |
| 5 | One configuration, constants declared a priori, no tuning | Held — see BUILD_RECORD.md |

### Criterion 1 detail

Pooled (n = 7,218): Brier full **0.2450** < base 0.2493, < Elo 0.2479 ✓;
log loss **0.6834** < base 0.6917, < Elo 0.6894 ✓; totals MAE **3.5386**
< league-average 3.5531 ✓; team-total MAE **2.4587** < 2.5057 ✓.

Per fold:

| Fold | Brier full / base / Elo / ctrl | LL full / base / Elo | Totals MAE full / base | Team MAE full / base | Leg |
|---|---|---|---|---|---|
| 2023 (n=2,400) | 0.2483 / 0.2498 / **0.2479** / 0.2450 | 0.6906 / 0.6928 / **0.6897** | 3.6004 / 3.6197 ✓ | 2.4785 / 2.5191 ✓ | **FAIL — Elo legs** (Brier and LL) |
| 2024 (n=2,405) | 0.2426 / 0.2496 / 0.2484 / 0.2430 | 0.6782 / 0.6923 / 0.6904 ✓ | **3.4218 / 3.4193** | 2.4173 / 2.4536 ✓ | **FAIL — totals MAE leg** (by 0.0025) |
| 2025 (n=2,413) | 0.2442 / 0.2484 / 0.2473 / 0.2430 | 0.6812 / 0.6899 / 0.6881 ✓ | 3.5935 / 3.6204 ✓ | 2.4803 / 2.5443 ✓ | PASS |

Calibration deciles (pooled, full model): deviations by decile
0.0547 / 0.0149 / 0.0006 / 0.0174 / 0.0079 / 0.0454 / 0.0000 / 0.0046 /
0.0474 / 0.0198 — all within the 7.5 pp gate at n ≈ 722 per decile.

The market-proxy leg uses the DESIGN-GRADE consensus closes of design
§5.1 (`minmaxxxer/mlb-closing-odds-2025`, CC BY 4.0, date-only, no
book): a scoring reference for the 2025 fold only, never a model input.
It does not close gap G4 and no CLV claim is drawn from it.

## Ablation table (design §5.3, pooled Brier; Δ = Brier(ablated) − Brier(full), paired bootstrap, 2,000 reps, seed 20261028)

| Variant | Brier | Log loss | Δ vs full [95% CI] | Reading under §5.3 |
|---|---|---|---|---|
| Full model | 0.2450 | 0.6834 | — | — |
| Lineup/platoon off | 0.2445 | — | −0.00058 [−0.00184, +0.00066] | removal does not hurt → would be dropped from a freeze candidate |
| Availability off | 0.2443 | — | −0.00070 [−0.00128, −0.00012] | removal significantly *helps* → would be dropped |
| Umpire off | 0.2451 | — | +0.00004 [−0.00004, +0.00011] | removal does not hurt beyond the interval → would be dropped |
| Weather off | 0.2450 | — | +0.00001 [−0.00009, +0.00012] | removal does not hurt beyond the interval → would be dropped (term active only in the 2025 fold; see below) |

The family failed the screen, so there is no freeze candidate for the
ablation rule to prune; the table is reported as the design requires.
The honest summary of the ablations: at this configuration the
PA-state inputs (lineup/platoon deltas and the availability pool) do
not add predictive value over the V1-shaped season-rate machinery on
these folds — the machinery control is the stronger model on every
fold's Brier, and the state components' removal is neutral-to-helpful.

The starter/bullpen-split lesson from V1 Phase D was applied as
designed (expected-innings phase share; availability-weighted bullpen
phase); the split machinery is part of both the full model and is not
separately ablated by the design.

## Weather input (design step B — pin record in `weather_pin_record.json`)

Open-Meteo Previous Runs `previous_day1` forecasts, pinned by hash
manifest (131 venue-season pulls; manifest sha256
1f05235dd415b6e9d93e2357a0afeb95f26e52e634016f32f2895345f4797a12),
availability labeled LEAD_TIME_BOUND. Observed actuals were never
pulled. Coverage finding: the endpoint serves wind/precipitation
`previous_day1` only from 2024 onward (temperature is served for
2022–2023), so under the declared NO_DATA → neutral handling the
weather term is inactive in the 2023/2024 folds and fitted on 1,763
fit-window rows for the 2025 fold (coefficients: intercept −0.1805,
temperature +0.0289 per 10°F above 70, wind-out +0.0253 per 5 mph,
precipitation +0.1148 — log-total multipliers, clamped ±0.25).

## Leak audit

- **Point-in-time discipline**: every fitted object (RE matrix, class
  linear weights and shares, park renormalization inputs, calibration
  layers, weather coefficients, Elo HFA, league constants) is fitted on
  the fold's fit window only; every in-season history updates strictly
  after the game it describes is scored (watermark assertion in code).
- **Truncation audit**: the 2024 fold was re-run with all data after
  2024-12-31 removed; all 2,405 test predictions are bit-identical
  (0 diffs).
- **Weather**: forecasts only (Previous Runs, lead-time bound ≥ 24h);
  actuals barred and never pulled.
- **Market proxy**: used only to score the 2025 fold after predictions
  were fixed; never a model input.
- **Data pins**: all inputs hashed in `data_manifest.json`; the PA
  census reproduces the PR #2900 proof exactly (733,260 PAs; per-season
  182,466 / 184,506 / 182,903 / 183,385); Retrosheet run totals agree
  with StatsAPI on 99.05–99.55% of matched games per season, with the
  residual disagreement set flagged per game and excluded from scored
  rows (histories still update; see BUILD_RECORD.md reading 2).

## Family status

MLB_GAME_STATE_V1: **FAILED_SCREEN** (historical design screen,
2023–2025 folds). No freeze, no forward clock, no counted rows. The
2027 forward-verification path in the design does not open from a
failed screen. Any successor construction is a new version, designed
against what this screen measured — most directly, that season-rate
machinery with a same-form calibration layer beat the PA-state
components as configured here.
