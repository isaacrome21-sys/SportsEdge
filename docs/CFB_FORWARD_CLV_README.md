# CFB_FORWARD_CLV_POLICY_V1 — forward evidence contract

Policy: `config/cfb_forward_clv_policy_v1.json`  
Current frozen version: `1.0.2`

The activation process computes the committed policy SHA-256 and binds every admissible evidence row to it. This document intentionally does not hard-code a pre-activation file hash.

## Scope

This policy defines how prospective CFB CLV/calibration evidence is collected. `CFB_TRUTH_GATE_V1` remains authoritative for promotion. Historical feature reconstruction/model selection is separate.

The first admissible slate is **2026-09-19**. Nothing from 2026-09-12 is admissible and no backfill is permitted. Purdue/Kentucky/UCF from Sep 12 remain RUN IT / Layer B only forever.

Raw market capture is not evidence by itself. A genuine hash-bound CFB `Model_P`, evidence unit, sealed decision row, and all Truth Gate prerequisites remain required before an evidence clock can start.

## Exact-contract CLV and alternate lines

A decision at +3 is graded against the closing price at +3. If the main line moves to +2.5, the close lane requests DraftKings `alternate_spreads` / `alternate_totals` so the original threshold can be recovered.

If the original contract is unavailable, the row is `CLV_MISSING` and stays in the coverage denominator. `NORMAL_APPROX_V1` is diagnostic-only and never promotion evidence.

## Close boundary: actual start, not scheduled kickoff

The frozen close window is **T-20m through T-0 actual start**. Scheduled kickoff only seeds monitoring.

A raw close snapshot is retained only when both sources independently say the event is still pre-start:

1. ESPN CFB scoreboard status is fresh and PRE_START; UNKNOWN/missing/stale/in-progress/postponed fails closed.
2. DraftKings exposes fresh, two-sided pregame h2h/spread/total markets at capture.

Raw close snapshots are append-only. After play begins, a separate first-play attestation artifact is written. `LAST_SUCCESSFUL_VALID_CAPTURE` is the deterministic latest raw snapshot strictly before the immutable first-play timestamp. A snapshot at or after first play is `INVALID_POST_START`, even if a live status feed lagged.

Delayed PRE_START games remain monitored after scheduled kickoff. A game postponed to another date is void for that date and must be captured again under the new window.

## Cluster inference

Each canonical market needs at least **12 independent slate clusters** before OFFICIAL inference, regardless of decision count. Twelve is a hard floor, not a sufficiency claim.

CR1 remains one-way clustered by `slate_date_ct`, but small-G inference uses Student-t with `df = G-1`; the effective two-sided 95% critical value is the larger of the frozen 2.0 t-stat floor and `t(0.975, G-1)`. IID fallback is prohibited.

## Capture workflow

Workflow: `.github/workflows/cfb-forward-clv-capture.yml`

- Monday 09:00 America/Chicago: FBS opener capture for the upcoming Saturday-through-Monday window.
- Every five minutes: free ESPN FBS/status gate; paid Odds API event/close calls only when a game is in the seeded close-monitoring window.
- Close request includes DraftKings `h2h`, `spreads`, `totals`, `alternate_spreads`, `alternate_totals`.
- Post-start runs write first-play attestation/selection artifacts.
- Capture artifacts append only to the `data` branch.
- No backfill; no overwrite; no Layer B import.

GitHub Actions cannot schedule more frequently than every five minutes. The lane therefore stores every valid scheduled raw snapshot it obtains and selects the latest snapshot that survives posthoc first-play attestation; it does not fabricate one-minute observations that were never captured.

## Known provider limitations — fail closed

The current Odds API transport does not expose verified DraftKings market-limit status. It also exposes a market-level update timestamp rather than independently timestamped two-sided outcomes. The collector therefore records:

- `BOOK_LIMIT_STATUS_UNKNOWN`
- `TWO_SIDED_SYNC_UNVERIFIED`
- `promotion_grade_quote_eligible=false`

Those raw prices remain diagnostics/capture plumbing, not promotion-grade CLV, until a verified source contract satisfies the frozen hygiene requirements. Nothing in the workflow invents a limit or a synchronization timestamp.
