# CFB research-rank challenger preregistration V1

Status: preregistration only. NOT Model_P. NOT Truth Gate. NOT OFFICIAL.

Policy ID: `CFB_RESEARCH_RANK_PREREG_V1`

This document freezes the evaluation contract required by #1069 before any CFB research-card ranking challenger is implemented or tested against outcomes.

## Locked semantic boundaries

1. `estimate_p` remains market-blind. No sportsbook spread, total, price, ticket %, handle %, RLM, steam, or handicapper output may enter model features.
2. The merged Score rule B remains qualification-only. Do not reuse the `Score` field as a predictive confidence score and do not add edge, EV, odds, market distance, or probability magnitude back into Score.
3. Any future challenger must use a separate field, provisionally `research_rank`, labeled `QUALITY_RANK_NOT_WIN_PROBABILITY`.
4. `research_rank` never creates Model_P, never grants Truth Gate authority, never changes eligibility, and never creates OFFICIAL/staking authority.
5. Market-informed external products may be displayed as context but cannot count as independent market-blind model votes.

## Eligible evaluation rows

A row is eligible only when all inputs used by the challenger were captured in an immutable artifact before kickoff. Missing source snapshots are `MISSING`; they are not reconstructed from postgame pages or later versions.

Required row properties:

- target game and kickoff identity are stable;
- SportsEdge prediction artifact predates kickoff;
- every challenger input has source/provenance and a pre-kickoff timestamp;
- outcome was unknown when the row was frozen;
- no outcome-informed backfill or manual relabeling occurred.

The Sept. 26, 2026 research card is regression evidence only. It is excluded from fitting, feature selection, threshold selection, weight selection, and attempt selection.

## Attempt budget

Maximum challenger budget: **3 attempts**.

The baseline does not consume an attempt. Before each challenger run, commit an immutable manifest containing the exact formula, inputs, missing-data behavior, bucket boundaries, and weights. Any post-result change to formula, weights, bins, source handling, or missingness policy consumes the next attempt. After attempt 3, stop; no fourth attempt may be created under this policy.

## Input restrictions for challenger manifests

Allowed candidate evidence is limited to pre-kickoff quality/reliability information, such as:

- immutable source freshness and completeness;
- dependence-adjusted external projection disagreement;
- sourced injury-status uncertainty/completeness;
- simulation sufficiency and distribution-quality diagnostics already available before kickoff.

Disallowed point-producing inputs:

- sportsbook edge, EV, American/decimal price, market spread/total distance, CLV, or realized ATS result;
- ticket %, handle %, RLM, steam, or handicapper/capper selections;
- raw count of agreeing projections when the sources are not demonstrated independent;
- post-kickoff injury, lineup, score, or outcome information.

For source dependence, Sasser/SP+ agreement must not automatically count as two independent votes. MySpariEdge is market-informed context only unless a future frozen audit demonstrates a market-blind component that can be isolated point-in-time.

## Pre-market evaluation gates

Because `research_rank` is ordinal and not a probability, do **not** compute Brier score or calibration slope on the rank itself.

Before historical market provenance is cleared, evaluate only whether higher rank identifies more reliable underlying SportsEdge forecasts:

- primary: monotonic relationship between rank and held-out joint-score log score (higher rank should correspond to better/lower log loss);
- secondary: monotonic relationship with absolute margin error and absolute total error;
- tier reliability: fixed bucket boundaries from the attempt manifest must show ordered mean forecast quality;
- stability: no material sign reversal by season, conference, home/away, and model-favorite/model-underdog strata;
- underlying `estimate_p` / score-distribution calibration must be unchanged because the challenger is ranking-only.

Fail closed if any candidate implementation changes the predictive distribution.

## Sample floor

Use the existing CFB governance floor as the minimum research evidence size: at least **4 forward seasons** and **200 eligible rows** overall. Any reported rank bucket must contain at least 50 eligible rows. If a bucket or stratum is below its floor, report `UNDERPOWERED`; do not merge buckets after seeing outcomes to manufacture significance.

## Market evaluation gates — BLOCKED until #1070 clears

ATS hit rate, no-vig CLV, ROI, favorite/dog market strata, and sportsbook spread buckets remain unavailable as acceptance gates until a historical closing-line source has verified closing semantics and provenance sufficient for the intended metric.

When #1070 clears, market evaluation may be added only by a new frozen appendix committed before those results are inspected. Historical line data remains evaluation-only and may never feed `estimate_p`.

## Acceptance rule

A challenger may advance from research only if all of the following are true:

1. PIT reproducibility: zero leakage violations.
2. Sample floor is met without outcome-dependent exclusions.
3. Rank ordering is monotonic on the primary forecast-reliability metric overall.
4. The ordering is not driven by a single season or conference.
5. No underlying predictive-distribution metric is degraded or altered.
6. The challenger formula was frozen before evaluation.
7. The attempt budget is not exceeded.

Until historical market provenance is cleared, a pass means only `RESEARCH_RANK_EVIDENCE_PASS`. It does not imply Model_P, Truth Gate, OFFICIAL, or positive betting expectancy.

## Stop conditions

Stop immediately and mark the attempt failed if:

- any required input is available only after kickoff;
- a source timestamp cannot be proven;
- market-derived values enter the point-producing rank formula;
- the challenger modifies `estimate_p` or simulation outcomes;
- a result-driven formula/weight/bin change is proposed without consuming the next attempt;
- three attempts are exhausted.
