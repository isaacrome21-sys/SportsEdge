# SportsEdge Research Backlog — Evidence Readiness First

Status at drafting: `INTEGRATION_UNRUN`.

Ranking rule: first by whether the idea is testable against evidence that will actually exist, then by expected value. Research does not become a coefficient, threshold, or promotion rule without the required sample.

Applies across ML, RL, full-game totals, F5 markets, team totals, NRFI/YRFI, pitcher Ks/outs/hits allowed/walks/ER, hitter hits/TB/HR/XBH/runs/RBI/walks/Ks/SB/H+R+RBI, and alternates.

## Tier 1 — testable now with existing architecture/data

1. **Double-holdout model/config selection**
   - Highest-value Tier 1 item.
   - Chronological grading holdout plus a second reserved holdout untouched by hyperparameter/config search.
   - Addresses model-selection bias.
   - Complementary to null-slate/rank-selection work, which addresses bet-selection bias.

2. **Leakage audits**
   - MLB residual layers and football M2.
   - Search for sportsbook line, total, implied probability, closing price, or any market-derived quantity entering predictive features where prohibited.
   - Any leak invalidates downstream evidence.

3. **Deterministic fixtures**
   - Frozen inputs and frozen market snapshot.
   - Same-input and irrelevant-environment variation tests.

4. **CLV / market-comparison plumbing**
   - Keep model quality and market comparison separate from realized ROI.
   - Manual-analysis bets do not enter the pipeline CLV series.

5. **Executable-price rules**
   - Preserve the #106 contract as research target: book, price, availability, max stake, timestamp.
   - Rejection classes: `NO_EXECUTABLE_QUOTE`, `QUOTE_UNAVAILABLE`, `LIMIT_TOO_LOW`, `EXECUTABLE_EV_TOO_SMALL`.

## Tier 2 — testable once archive flow resumes

1. **Power and Shin devig**
   - Compare with `MULTIPLICATIVE_V1`.
   - Treat method disagreement as uncertainty in fair probability, not as an excuse to select the method that makes a bet pass.

2. **Market-family calibration**
   - Hard floor `n >= 300` eligible settled pipeline observations per market family.
   - Below that: `INSUFFICIENT_EVIDENCE`.
   - Do not present fitted calibration as decision evidence below the floor.

3. **Hierarchical blend weights**
   - Candidate hierarchy: global -> market -> price bucket.
   - Walk-forward only.
   - Bucket relationship must be predeclared/monotone where used; no opportunistic fitting after results are seen.

4. **Null-slate rank penalty**
   - Version to the declared market surface.
   - Handles selection among many candidate bets; distinct from double-holdout model selection.

## Tier 3 — requires richer point-in-time inputs

1. **Handedness-split pitcher K models**
   - Statcast K% split by batter handedness combined with pitch/arsenal quality inputs.
   - Requires point-in-time lineups and pitcher arsenal inputs.

2. **Catcher framing and umpire context**
   - Umpire influence remains capped at +/-4% pending forward evidence.
   - No reliable free pregame umpire feed is assumed.
   - Missing umpire is an `INPUT_MISSING`-tolerant state where the model contract allows it; stale prior-day assignments must never be carried forward.

3. **Bullpen/workload refinements**
   - Same-day availability, recent pitch counts, role, leverage usage, starter leash/workload prior.

## Tier 4 — long-horizon validation

1. **Batter-level park factors**
   - Park effect depends on the hitter's batted-ball profile, not venue alone.
   - Most relevant for HR and TB/XBH read-outs.
   - Requires batter-level spray/contact profiles plus enough player-park outcomes for honest validation.

2. **Spray-profile HR/TB effects**
   - Pull/center/opposite-field interaction with park geometry and weather.

3. **Player-specific environment models**
   - Neutral contact model vs environment-aware contact model; environment delta is learned at batter/contact level.
   - Long sample requirement; do not fit from tiny player-park slices.

## Calibration discipline

`Calibrate` means recommend coefficient/weight changes only when the prespecified evidence floor exists. Otherwise the item remains `BACKLOG_HYPOTHESIS` or `CANDIDATE_REFINEMENT`.

No threshold is relaxed to increase bet count. No research item silently enters production. No market-specific fudge factor is permitted on a read-out from the shared simulator.

## Status convention

Each backlog item carries three independent states:

- `PRESENT`: design/spec exists in repo or branch.
- `EXECUTED`: the relevant test or evaluation actually ran.
- `EVIDENCE`: durable result meeting its prespecified evidence rules exists.

A spec can be PRESENT while EXECUTED=NO and EVIDENCE=NO.
