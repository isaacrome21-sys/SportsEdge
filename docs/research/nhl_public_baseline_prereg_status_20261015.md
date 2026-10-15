# NHL public baseline prereg v1 — implementation status and gaps (2026-10-15)

Research only. No data fetched, nothing scored. Base: main `f113a3e8`.

## Status

- Prereg `config/research/nhl_public_baseline_validation_prereg_v1.json`
  (FROZEN_BEFORE_IMPLEMENTATION) and protocol
  `..._protocol_v1.json` (FROZEN_BEFORE_FIRST_REAL_DATA_EVALUATION) are
  **already implemented on main** by `sportsedge/sports/nhl/public_baseline_validation.py`
  and `scripts/validate_nhl_public_baseline.py` (commit `4d57d581`, PR #1816 lineage),
  and bound in `config/freeze_reconciliation_registry_v1.json`
  (`NHL_PUBLIC_BASELINE_VALIDATION_RESEARCH_FREEZE_V1`, freeze_sha `378a6386`).
  Its tests pass on main (`tests/test_nhl_public_baseline_validation.py`,
  `tests/test_nhl_public_baseline.py`: 5 passed). No new harness was written:
  re-implementing a frozen, freeze-bound harness would create a competing path.

## Data

- No official NHL boxscore receipts exist in the repo, on the `data` branch, or
  on the box. The only source is `scripts/collect_nhl_official_boxscores.py`
  (free public `api-web.nhle.com`, not credit-consuming). It was **not run**.
- Running the collector + validator as written would fit on games before
  2025-07-01 **and score the 2025-10-01 → 2026-05-01 holdout in the same call**.
  The script has no fit-only mode, so no part of it can run without scoring
  the holdout. It therefore waits for the owner.

## Gaps in the frozen prereg (cannot be fixed without an owner amendment)

1. **No pass criterion.** `promotion_boundary` says passing "may create research
   owner", but no threshold, comparator or CI rule defines passing. As written
   the run can only report numbers, not a verdict.
2. **No baseline comparator.** Metrics are absolute (MAE, RMSE, Poisson NLL);
   no league-average / team-average / home-ice-only baseline is named, so
   "beats public baselines" cannot be assessed under this prereg.
3. **Holdout role is "REUSED_RETROSPECTIVE_DEVELOPMENT_HOLDOUT"** — by its own
   label it is not forward or betting evidence; any verification still needs a
   forward record from the 2026-27 season.
4. Target is regulation goals only: ML/puck line/total (OT/SO) are not evaluated.

## Needs owner authorization

- Go/no-go to run the free collector for 2023-10-01 → 2026-04-30.
- Go/no-go to score the holdout as written (numbers only, no verdict), **or**
  an amendment v2 adding a comparator + pass rule frozen before scoring.
- Forward capture plan for 2026-27.
