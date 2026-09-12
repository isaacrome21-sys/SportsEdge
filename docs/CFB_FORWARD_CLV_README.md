# CFB_FORWARD_CLV_POLICY_V1 — forward evidence contract

Policy: `config/cfb_forward_clv_policy_v1.json`  
Current frozen version: `1.0.3`

The activation process computes the committed policy SHA-256 and binds every admissible evidence row to it. This document intentionally does not hard-code a pre-activation file hash.

## Scope

This policy defines how prospective CFB CLV/calibration evidence is collected. `CFB_TRUTH_GATE_V1` remains authoritative for promotion. Historical feature reconstruction/model selection is separate.

The first admissible slate is **2026-09-19**. Nothing from 2026-09-12 is admissible and no backfill is permitted. Purdue/Kentucky/UCF from Sep 12 remain RUN IT / Layer B only forever.

Raw market capture is not evidence by itself. A genuine hash-bound CFB `Model_P`, evidence unit, sealed decision row, and all Truth Gate prerequisites remain required before an evidence clock can start.

## Exact-contract CLV and alternate lines

A decision at +3 is graded against the closing price at +3. If the main line moves to +2.5, the close lane requests DraftKings `alternate_spreads` / `alternate_totals` so the original threshold can be recovered.

If the original contract is unavailable, the row is `CLV_MISSING` and stays in the coverage denominator. `NORMAL_APPROX_V1` is diagnostic-only and never promotion evidence.

## Close boundary: actual start, not scheduled kickoff

The frozen close window is **T-20m through T-0 actual start**. Scheduled kickoff only seeds monitoring. Selection is deterministic: `LAST_SUCCESSFUL_VALID_CAPTURE` after every live and posthoc check.

A candidate close snapshot remains provisional only when both independent live checks pass:

1. ESPN CFB scoreboard status is PRE_START and no older than 30 seconds.
2. DraftKings still exposes the requested pregame contract as an open, two-sided market from the same source used for the price.

UNKNOWN, missing, stale, delayed-without-reliable-anchor, in-progress, suspended, one-sided, or otherwise unverifiable candidates fail closed. If no candidate survives, the decision row stays in the denominator as `CLV_MISSING`; no backfill or inferred close is permitted.

## Stabilized first-play attestation

ESPN play-by-play is not treated as immutable upstream data. The attestation is fetched no earlier than **12 hours after final status**, then canonicalized, hashed, and sealed as the settlement snapshot. Earlier reads are diagnostic only and cannot validate evidence.

Timestamp precision is part of admissibility. The first-play timestamp must have known uncertainty <=30 seconds, and the quote must satisfy:

`quote_ts <= first_play_ts - (timestamp_uncertainty_seconds + 30 seconds)`

Missing or ambiguous precision, uncertainty >30 seconds, an unstable/revised source at seal time, or a comparison inside the uncertainty margin is `INVALID_ATTESTATION_UNVERIFIED`. A quote at or after first play is `INVALID_POST_START` even if the live ESPN status lagged.

Delayed games re-anchor only when there is a verified updated kickoff. If a game remains delayed with no reliable new anchor, polling continues and scheduled time is not treated as the close. A game postponed to another date is `VOID_POSTPONED`; the old close cohort is never reused and the game must be recaptured under the new date/window.

## Provider failure matrix

- ESPN status missing/stale: candidate `INVALID_STATUS_UNVERIFIED`; no surviving candidate => `CLV_MISSING` retained in denominator.
- ESPN status in progress: candidate `INVALID_POST_START_STATUS`.
- DraftKings requested pregame market missing/suspended/one-sided: candidate `INVALID_BOOK_STATE`; no surviving candidate => `CLV_MISSING` retained in denominator.
- Both live sources pass: candidate remains provisional until stabilized first-play attestation.
- Attestation missing/ambiguous/unstable: candidate `INVALID_ATTESTATION_UNVERIFIED`; no surviving candidate => `CLV_MISSING` retained in denominator.

## Cluster inference and postseason regime

Each canonical market needs at least **12 eligible regular-season slate clusters** before OFFICIAL inference, regardless of decision count. Twelve is a hard floor, not a sufficiency claim.

Conference championships, bowls, and playoff games are `POSTSEASON_DIAGNOSTIC_ONLY` and cannot be pooled into the primary regular-season promotion ledger merely to reach cluster 12. If 12 eligible regular-season clusters are unavailable in 2026, OFFICIAL remains unavailable.

CR1 remains reported and its frozen CLV t-stat >=2.0 gate remains required. Small-G significance also requires deterministic wild-cluster-bootstrap-t with Webb six-point weights, 9,999 repetitions, and two-sided p<=0.05. The seed is versioned and bound to policy SHA plus market ledger. Bootstrap cannot rescue a failed mean-CLV or CR1 t-stat gate.

## Capture workflow

Workflow: `.github/workflows/cfb-forward-clv-capture.yml`

- Monday 09:00 America/Chicago: FBS opener capture for the upcoming Saturday-through-Monday window.
- Scheduled close monitoring must enforce the live ESPN/DraftKings dual-source gate.
- Close request includes DraftKings `h2h`, `spreads`, `totals`, `alternate_spreads`, `alternate_totals`.
- Settlement must create the stabilized first-play attestation before any raw close can become admissible.
- Capture artifacts append only to the `data` branch.
- No backfill; no overwrite; no Layer B import.

GitHub Actions cannot guarantee one-minute cadence, so the lane may only select from observations actually captured. It must never fabricate a closer observation.

## Known provider limitations — fail closed

The current Odds API transport does not expose verified DraftKings market-limit status. It also exposes a market-level update timestamp rather than independently timestamped two-sided outcomes. The collector therefore records:

- `BOOK_LIMIT_STATUS_UNKNOWN`
- `TWO_SIDED_SYNC_UNVERIFIED`
- `promotion_grade_quote_eligible=false`

Those raw prices remain diagnostics/capture plumbing, not promotion-grade CLV, until a verified source contract satisfies the frozen hygiene requirements. Nothing invents a limit or synchronization timestamp.

## Merge gate

Do **not** merge while runtime behavior lags policy v1.0.3. `scripts/cfb_forward_clv_capture.py`, workflow polling/scheduling, settlement attestation, provider-failure states, postseason regime handling, bootstrap inference, and tests must enforce the frozen policy before merge. A green artifact that merely asserts these semantics is insufficient.
