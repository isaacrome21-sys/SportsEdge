# SportsEdge CFB Base Artifact and Validation Gate V1

Status: **TIER-0 HARD GATE**

This document freezes the dependency order for the CFB predictive stack. No personnel, injury, travel, officiating, external-model, props, live, or other downstream overlay may become `Model_P` until this gate is satisfied.

## 1. Canonical frozen artifact contract

The only default runtime artifact path is:

`models/cfb_joint_v1.json`

The builder and AUTO runner must import the same canonical path constant. A missing artifact is a hard stop and must produce a fail-closed blocked run. Runtime fitting is prohibited.

The frozen artifact must be produced from a declared point-in-time training bundle and must contain or bind:

- artifact schema version
- model id
- feature contract
- model code-surface SHA-256
- training-source SHA-256
- frozen model payload
- artifact SHA-256

The accompanying training-provenance record must preserve at minimum:

- training-bundle SHA-256
- upstream source-manifest SHA-256
- `fit_max_season`
- training row count
- build configuration including ridge alpha
- observation/source identity sufficient to replay the build

For the 2026 production candidate, the training cutoff may not include 2026 outcomes. The intended maximum training season is 2025 unless a separately frozen protocol explicitly chooses an earlier cutoff.

No artifact may be hand-authored, reconstructed from market outcomes, or generated from data observed after its declared cutoff.

## 2. Base-model temporal validation

Historical evaluation uses expanding-window, season-based walk-forward splits over the currently declared 2014-2025 historical range.

Predeclared folds:

- test 2015, train through 2014
- test 2016, train through 2015
- ...
- test 2025, train through 2024

That produces 11 chronological test folds. Every feature used in a test game must satisfy its point-in-time availability rule. No future-season or closing-market information may enter model features.

Where the existing SportsEdge M1/M2 comparison applies, the candidate must beat the baseline on log loss in at least 65% of folds for the market being considered. With 11 folds this means at least 8 fold wins. This is a model-comparison gate, not a claim of profitability.

## 3. Required market-level reporting

Report separately for moneyline, spread, and total; do not pool the markets to hide a weak component.

Required probability-quality outputs:

- Brier score
- log loss
- reliability/calibration diagram
- calibration slope
- calibration intercept
- expected calibration error (ECE)
- sample count by season/fold

Required market/execution outputs once point-in-time decision and close quotes exist:

- no-vig decision probability
- no-vig closing probability
- no-vig CLV
- CLV standard error / t-statistic
- after-vig realized ROI
- bet count
- price/line distribution

After-vig ROI is a reporting metric, not a promotion gate under the current football roadmap because realized betting ROI is too noisy to use as the sole or mandatory promotion criterion.

## 4. Deployment evidence gate

Current canonical deployment evidence requirements remain:

- at least 200 logged forward/eligible decisions for the market
- mean no-vig CLV > 0
- CLV t-statistic > 2

No backfill may count as untouched forward evidence. The forward holdout begins only after the frozen artifact, decision-time capture contract, and evidence writer are active.

## 5. Calibration thresholds

The following thresholds may be used as governance diagnostics while research proceeds:

- calibration slope: 0.90 to 1.10
- absolute calibration intercept: <= 0.03
- ECE: <= 0.025

Their status is `PROVISIONAL_GOVERNANCE_THRESHOLD`, not `EMPIRICAL_THRESHOLD`. They may not be described as empirically derived until a predeclared derivation study names its data, observation window, estimator, sample floor, and untouched check.

Brier and log-loss acceptance should be judged against the frozen baseline and across chronological folds rather than by an invented universal numeric cutoff.

## 6. Forward evidence integrity

Every forward record used for promotion must bind:

- frozen model artifact SHA
- model code-surface SHA
- source/training identity
- decision timestamp
- exact book, line, and price
- no-vig market probability
- SportsEdge probability before context/editorial layers
- eventual closing quote captured point-in-time
- result only after the event

External projections, public/sharp splits, capper opinions, and later line movement are not model features and cannot repair a missing decision-time record.

## 7. Downstream unlock order

Only after the base artifact exists and the base model has legitimate OOS/forward evidence may downstream candidates advance in this order:

1. pace / expected possessions
2. explosive plays / finishing drives
3. opponent-adjusted trenches
4. coverage / receiver interaction
5. special teams
6. market microstructure / price execution
7. garbage-time / blowout distribution
8. travel/circadian, injury uncertainty, and officials as validated transforms

Personnel/injury v0.1 remains `SHADOW_RESEARCH_ONLY`, `model_p=false`, `promotion_eligible=false` until its own OOS test is performed on top of a validated base.

## 8. Current blockers

As of 2026-09-05:

- no frozen `models/cfb_joint_v1.json` is checked into the working base branch
- therefore canonical CFB AUTO remains correctly fail-closed
- the CFB CI workflow references CFB-specific test paths that are not currently present on `main`; this is a CI-contract gap that must be reconciled rather than silently ignored
- GitHub-hosted workflow execution is also externally blocked by runner-allocation failures, so a queued workflow without an assigned runner is not test evidence

None of these blockers may be converted into a pass by external model agreement or manual confidence.
