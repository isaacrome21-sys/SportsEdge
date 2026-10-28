# SCREEN REPORT — UFC moneyline flagship, Leg 1 historical design screen

**Family:** `UFC / MONEYLINE_H2H` · **Construction:** `UFC_ML_PIT_RATING_V1`
(the existing engine's learner — `sportsedge.ufc_training.fit_logistic`
over its frozen `FEATURES` diffs; features rebuilt point-in-time by
`sportsedge.ufc_history`)
**Design:** `research/new_sports_designs_20261027/UFC_MONEYLINE_DESIGN_PREREG_DRAFT.md`
§6 Leg 1 · **Criteria:** `config/ufc_promotion_contract_v1.json`, read at
run time and adopted verbatim
**Market baseline provenance:** `RECORDED_PRICE_NOT_DK_CLOSE` (everywhere
below — the dataset does not document book or timestamp)

## Verdict: FAILED_SCREEN

`UFC_ML_PIT_RATING_V1` **fails Leg 1**. It beats the Elo-only reference
(log loss 0.6443 vs 0.6821), so the career-rate features carry signal
beyond Elo — but it loses clearly to the recorded market prices on both
gated deltas, and its flat-bet ROI at the recorded prices is negative.
Per the draft §6, a FAIL is recorded as `FAILED_SCREEN` and V1 retires;
no Leg 2 (forward DraftKings leg) proceeds for this construction, and any
successor is a new construction with its own preregistration. Nothing was
promoted and nothing was frozen by this screen.

## Criterion-by-criterion (test window 2023-01-01 → 2025-12-31)

| Criterion (contract) | Required | Observed | Verdict |
|---|---|---|---|
| Test n (`holdout_n_min`) | ≥ 500 | 1,291 | PASS |
| Debut slice n (`debut_n_min`) | ≥ 100 | 231 | PASS |
| Calibration error (`calibration_error_max`) | ≤ 0.05 | 0.0405 | PASS |
| Brier delta vs market (`max_brier_delta_vs_market`) | ≤ 0.0 | **+0.0247** (model 0.2263 vs market 0.2016) | **FAIL** |
| Log-loss delta vs market (`max_log_loss_delta_vs_market`) | ≤ 0.0 | **+0.0556** (model 0.6443 vs market 0.5887) | **FAIL** |
| Log loss strictly better than Elo-only (draft §6) | model < Elo-only | 0.6443 < 0.6821 | PASS |
| Flat-bet ROI at recorded prices (draft §6, reported) | > 0 | **−0.0218** (−28.10u on 1,291 1u bets, 803 wins, argmax rule) | FAIL (also fails if read as a gate) |

Full precision lives in `screen_results.json`; model metrics were
cross-checked against the repo's own evaluator
(`sportsedge.ufc_training.evaluate`) and agree exactly.

## Protocol as executed

- **Splits (chronological, untouched test):** fit ≤ 2019-12-31 (3,809
  scored rows) → Platt calibration only on 2020-2022 (1,355) → test
  2023-2025 (1,291). No test row influenced fitting or calibration.
- **Scored rows:** point-in-time training rows built from the pinned
  per-fight record (7,556 rows, 2010 → 2026-10-24), joined to recorded
  prices by date + unordered fighter pair: 6,571 joined, 6,569 with
  both sources agreeing on the winner; the **2 disagreements were
  excluded and counted**, never resolved silently; 985 rows had no
  priced counterpart. Draws / no-contests never become training rows
  and are excluded structurally.
- **Features:** rebuilt from the per-fight record strictly before each
  bout's date (the history builder snapshots state before updating it).
  Odds are evaluation-only and never enter the feature vector.
  Readings recorded: (a) the feature vector is the engine's frozen
  `ufc_training.FEATURES` — the snapshot's knockdown/control fields
  exist but are not in that vector, and its `late_replacement` diff is
  structurally zero in historical data (no booking-change source);
  (b) debut fighters enter with the engine's existing prior treatment
  (zeroed rates, 1500 Elo, 0.5 recent-form/SoS defaults) — §4's "class
  medians" wording has no operational counterpart in the engine.

## Data — pins and mirror verification

Kaggle keys are not available on this machine (repo Actions secrets
only), so the Kaggle pull route could not be used. The screen ran on
**lawful public GitHub mirrors, commit-pinned and hash-verified before
use** (`PINS.json`; the repo stores hashes only):

- **Market / outcomes:** the dataset author's own GitHub mirror of
  Kaggle `mdabbert/ultimate-ufc-dataset` (`shortlikeafox/ultimate_ufc_dataset`
  @ `31d29415…`; the repo's README links the Kaggle page and its
  `dataset-metadata.json` carries the Kaggle id/owner, CC BY 4.0).
  `ufc-master.csv`: 3,190,849 B, sha256 `b8aa6604…`. Verified against
  the design's stated dataset shape: 7,177 rows, **6,924 priced rows**
  (design: ~6,900+), dates 2010-03-21 → 2026-03-28, Winner ∈ {Red,
  Blue, Draw} plus 3 No Contest rows, recorded odds + derived profit
  columns present. Kaggle-side byte equality is unverifiable without
  keys; the pin attests the mirror bytes as pulled 2026-10-28.
- **Per-fight record (features + audit):** `Greco1899/scrape_ufc_stats`
  @ `5d6622ff…` — the same UFCStats mirror the repo's production
  history pipeline (`sportsedge/ufc_history.py`) already consumes; four
  CSVs hash-pinned in `PINS.json`. No site was scraped for this screen.

## Section 5 pre-screen audit — shipped aggregates DISCARDED

Before any fitting, the market dataset's shipped career aggregates were
compared against aggregates rebuilt from the per-fight record over the
full population: **12,170 row-sides, 1,960 distinct fighters**.

- Entering W/L/D matches the rebuilt record exactly in only **78.9%**
  of checks (9,607/12,170). Example: on 2026-03-28 the dataset ships
  Joe Pyfer at 7-2 while the UFCStats per-fight record rebuilds 6-1;
  the same +1-win pattern repeats across fighters — the shipped record
  columns are not the UFCStats point-in-time record.
- `avg_SIG_STR_landed` has **mixed units inside one column**: of
  row-sides with ≥3 prior bouts, 4,378 match the rebuilt *per-fight*
  average within 10%, 3,354 match the rebuilt *per-minute* rate within
  10%, and 1,135 match neither. (Spot pattern: Georges St-Pierre's
  rows ship ≈55, a per-fight average; Jon Jones's ship ≈4.3, a
  per-minute rate.)
- Rate agreement is weak even where units are unit-free: sig-strike
  pct within 0.03 of rebuilt in 69.4% of checks; takedown pct in 46.2%.

**Audit verdict: the shipped aggregates are not point-in-time
consistent and were discarded wholesale**, exactly as draft §5
prescribes. The construction uses rebuilt features only, so the screen
proceeded; no number in this report derives from a shipped aggregate.

## Slices (diagnostic only, per draft §7)

| Slice | n | Model LL | Market LL | Model Brier | Market Brier |
|---|---|---|---|---|---|
| All test | 1,291 | 0.6443 | 0.5887 | 0.2263 | 0.2016 |
| UFC debut (either fighter) | 231 | 0.6650 | 0.5752 | 0.2341 | 0.1963 |
| Male | 1,095 | 0.6456 | 0.5914 | 0.2268 | 0.2030 |
| Female | 196 | 0.6371 | 0.5737 | 0.2232 | 0.1941 |
| 3-round | 1,150 | 0.6441 | 0.5848 | 0.2262 | 0.1998 |
| 5-round | 141 | 0.6462 | 0.6207 | 0.2273 | 0.2165 |

Per-weight-class numbers are in `screen_results.json`. Note the debut
slice: the design §2 hypothesized the edge would be largest exactly
where market information is thinnest (debuts, low-profile fighters) —
the measured deficit against the market is instead the **largest** of
any slice. The mechanism, as constructed, does not show up where it was
supposed to.

## Contract terms reported (not gated in Leg 1)

- **Training-data max age (45 days):** newest calibration bout
  2022-12-17 → test start 2023-01-01 = **15 days**, within the limit
  under the Leg 1 reading; the term binds the forward promotion act.
- **Closing-market provenance:** Leg 1 is scored against
  `RECORDED_PRICE_NOT_DK_CLOSE` by the design's own §3/§6 terms; the
  genuine closing-provenance requirement stands for Leg 2 / promotion.
- **Short-notice slice:** neither pinned source records booking
  changes, so the slice is **NOT_IDENTIFIABLE** historically; reported
  as required and not gated, per draft §6 Leg 1. (The contract's
  hard-gate language for missing short-notice evidence binds the
  promotion act, which this screen does not reach.)

## Reproduce

```
# pull the five files listed in PINS.json from the pinned commits
# (raw.githubusercontent.com URLs), place them in a data dir, then:
python3 research/ufc_moneyline_screen_20261028/run_screen.py --data-dir <dir>
```

The runner verifies every file's size + sha256 against `PINS.json`
before use, runs the §5 audit, rebuilds features, fits, and rewrites
`screen_results.json`. Deterministic (the engine's learner is fixed
gradient descent; no randomness anywhere in the pipeline).

*Evidence state: builder-executed screen run on hash-pinned mirror
bytes, 2026-10-28; awaiting Rocky's clearance review. No promotion, no
freeze, no clock started.*
