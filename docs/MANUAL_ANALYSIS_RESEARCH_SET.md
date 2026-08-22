# Manual-Analysis Research Set

Status at drafting: `INTEGRATION_UNRUN`.

This file records only what is supportable from the known history. It is not a model ledger and must never be upgraded into one retroactively.

Research rows are stored separately at `research/manual_analysis_ledger.csv` on the research branch.

## Source rule

All prior played bets discussed before the pipeline ledger existed are `source=manual_analysis` unless a contemporaneous SportsEdge pipeline artifact proves otherwise.

For `manual_analysis` rows, the following fields are null by construction unless they were durably captured at bet time:

- `model_probability`
- `model_version`
- `model_commit_sha`
- `config_hash`
- pipeline CLV attribution

They must never be backfilled from later analysis, reconstructed odds, or hindsight.

## Known research findings

- A prior stretch was summarized as **1-6**.
- A **SEA/HOU NRFI** bet was reported as a loss.
- Those plays were not reconstructible as pipeline decisions with contemporaneous Model_P/version identity.

The available information does not establish whether the SEA/HOU NRFI loss is inside or outside the summarized 1-6 stretch. The ledger therefore records the 1-6 item as an aggregate summary rather than manufacturing seven synthetic bet rows, and it flags the NRFI relationship as unresolved.

## Current manual tickets recorded without model backfill

The research ledger also records the manually confirmed Aug. 21 tickets for which the conversation establishes selection/price, while leaving unknown stake/timestamp/result fields blank:

- Padres ML -118
- CIN/ARI Under 8.5 -118
- PIT/LAD Under 8 -106
- Cubs ML -102
- Mariners ML -105 as a cash-out execution event

These remain research rows regardless of result. No fair probability, edge, EV, Kelly, grade, or pipeline PASS/BET label is attached.

## What may be logged later

If exact sportsbook tickets, timestamps, odds, stake, market identity, and settlement are available from contemporaneous records, they may be added as research rows with `source=manual_analysis`. Missing model fields remain null.

Parlays and boosts are recorded separately from straight bets and never become core model-calibration observations.

## What this set cannot be used for

Manual-analysis records MUST NOT enter:

- Brier score,
- log loss,
- fitted calibration,
- model-selection holdouts,
- V6/V7 promotion evidence,
- the first pipeline CLV series,
- any denominator used to satisfy an evidence floor.

The honest conclusion is already established: the prior plays were not reconstructible. This separation is the reason the ledger contract exists.

## Three statuses

- PRESENT ON MAIN: **NO — research-branch ledger only**
- RUNTIME EXECUTED: **NO — ledger write is documentation/data entry, not pipeline execution**
- PRODUCING EVIDENCE: **NO — manual rows are prohibited from promotion/calibration evidence**
