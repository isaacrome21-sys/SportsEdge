# MLB Refinement Audit — 2026-08-20

## Scope

This document records research-only refinements derived from durable SportsEdge evidence plus the 2026-08-20 hybrid-card postmortem. It does **not** promote any model, alter production deployment eligibility, relax edge floors, or change V6 gates.

The purpose is to convert recurring failure modes into explicit features and fail-closed contracts, then validate them point-in-time before any production use.

## Durable evidence reviewed

### NRFI/YRFI forward shadow

Latest durable NRFI/YRFI report: run `32044425549`, generated 2026-08-17T16:07:54Z.

- selected unique games: 63
- settled unique games: 53
- coverage: 0.984375
- evidence age: 4 days at report generation
- V5 Brier: 0.2417690621600849
- V6 Brier: 0.24895683387303955
- V5 log loss: 0.6766609655390003
- V6 log loss: 0.6910604172419142
- V6 eligibility: false

Across the settled rows, V6 repeatedly raises YRFI probability by roughly three percentage points relative to V5. The paired proper scores are worse, so a broad/global probability lift is not supported. Future NRFI/YRFI work should focus on conditional first-inning hazards rather than another blanket offset.

### Pitcher walks forward shadow

Latest durable PITCHER_BB report contains broad multi-game pitcher evidence and passes its overall calibration check, but has no paired Brier/log-loss comparison in the latest persisted report (`n=0` for paired metrics) and is also too young for promotion. It remains research evidence only.

### Settlement semantics

Durable settlement semantics already prove SportsEdge can settle the markets needed for later postmortems, including NRFI/YRFI, pitcher K/BB/outs/ER/hits allowed, batter markets, ML/RL/totals and F5 markets. Settlement capability is not the same thing as a multi-week prediction ledger.

## 2026-08-20 diagnostic outcomes

The daily card is used only to identify architecture weaknesses; coefficients are not fit to one day's outcomes.

Observed diagnostic examples:

- Gavin Williams strikeout over succeeded while SF-CLE NRFI failed. Pitcher strikeout quality and first-inning run prevention must remain separate predictions.
- Cleveland scored three in the first despite a strong full-game run-suppression profile. NRFI needs explicit top-of-order and first-time-through-order hazard.
- OAK-KC NRFI failed while the full-game under pushed. Full-game run environment cannot substitute for inning-specific hazard.
- Shane Bieber exceeded the outs-under projection by working seven efficient innings. Pitcher-outs models need manager leash, pitch ceiling and pitches-per-PA rather than only an innings mean.
- Anthony Kay reached the outs-over threshold but missed the strikeout over by one. Workload and strikeout expectation must be modeled separately.
- A DraftKings total-bases ladder was manually misread during hybrid analysis. Every player prop must bind player + market + side + exact threshold + exact price. Ambiguity is a fail-closed state.

## Refinements implemented on research branch

`mlb-refinement-history-audit-20260820` adds `sportsedge/mlb_refinement.py` with research-only diagnostics:

1. **Exact ladder identity** — `VerifiedSelection` and `assert_unique_ladder()` require exact player/market/side/line/odds/time/book identity and reject conflicting prices for the same rung.
2. **First-inning hazard** — top-three xwOBA, ISO, BB%, barrel%, starter first-inning BB/HR rates, first-time-through wOBA, platoon share, lineup confirmation and first-inning power environment are modeled separately from full-game quality.
3. **Starter leash** — recent pitch ceiling, 95+ pitch frequency, pitches per PA, recent outs, bullpen rest and manager hook tendency produce a research leash score.
4. **Strikeout expectation** — expected batters faced is multiplied by batter-specific K probabilities and a bounded pitch-quality multiplier; outs are not reused as a K prediction.
5. **Weather decomposition** — run environment and first-inning power are separate effects; a closed roof nulls wind effects; source disagreement shrinks environmental adjustments toward neutral.
6. **Cross-market conflict assessment** — hitter attack, first-inning hazard, model disagreement, unconfirmed lineups and weather disagreement can only reduce confidence. They cannot manufacture an edge.
7. **Research-adjusted edge** — confidence penalties shrink raw model edge toward zero. Negative edges remain negative.

## What is intentionally NOT changed

- `config/deployments.json`
- `config/truth_gate_floors.json`
- V6 eligibility criteria
- V5/V6 production probabilities
- production `decide_bet()` semantics
- any historical outcomes or labels

No result from Aug. 20 is allowed to retrospectively alter a pregame feature row.

## Missing evidence and next requirement

SportsEdge does not yet have a complete durable multi-week **bet ledger** for every hybrid market. The repository has strong settlement capability and partial forward-shadow evidence, but that is not equivalent to weeks of timestamped recommendations with exact offered prices.

Before coefficient fitting, create a point-in-time ledger where every candidate records:

- prediction/model SHA and feature-contract SHA
- generated-at and first-pitch timestamps
- market, side, exact line and exact offered price
- no-vig market probability
- model probability and raw edge
- conflict flags and confidence multiplier
- lineup/weather/umpire freshness state
- final settlement
- closing price when available

Analysis should then be segmented by market and feature regime using Brier/log loss/calibration for probabilities, MAE/distribution diagnostics for count markets, and CLV only as a secondary market-quality diagnostic. ROI must not become a promotion criterion.

## Validation rule

These refinements are hypotheses until they beat the current baseline on point-in-time walk-forward or untouched holdout data. A refinement that improves one day's win rate but worsens proper scoring, calibration, or holdout performance is rejected.
