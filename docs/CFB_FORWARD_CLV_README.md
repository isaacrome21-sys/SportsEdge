# CFB_FORWARD_CLV_POLICY_V1 — what this does and does not do

Commit path: `config/cfb_forward_clv_policy_v1.json`

Policy version: `1.0.1`
File sha256 as prepared for this PR: `92ff983b5f4d8615bfb35ca072470e9a74181f3809448397bfe9ceeedc2fb63b`
(CI recomputes the committed policy SHA at activation and every admissible evidence row must bind it.)

## What it does

It defines the forward evidence source for CFB when paired historical closing-line replay is unavailable. It does not change CFB_TRUTH_GATE_V1. Historical feature reconstruction/model selection is a separate problem; this file governs prospective CLV/calibration evidence only.

The first admissible slate is **2026-09-19**. Nothing from 2026-09-12 is admissible, and there are no backfills.

## Alternate-line capture at close

Exact-contract CLV is authoritative: a decision at +3 is graded against the closing price at +3. If the main line moves to +2.5, the close collector must fetch the alternate-line ladder and recover +3 from that ladder.

If the original contract is not posted, the row is `CLV_MISSING` and remains in the coverage denominator. `NORMAL_APPROX_V1` is diagnostic-only; it is never promotion evidence.

## Cluster count is a floor, not sufficiency

The policy requires at least **12 independent slate clusters** before OFFICIAL inference, regardless of decision count. At exactly 12 clusters, CR1 is still a small-G problem, so version 1.0.1 freezes a Student-t small-sample reference with `df = G-1`; the effective 95% critical value is the larger of the frozen t-stat floor and `t_0.975,G-1`.

No IID fallback is permitted.

## Layer B stays outside

Purdue / Kentucky / UCF from 2026-09-12 are HYBRID / Layer B rows. They are permanently inadmissible to this ledger and belong only in the RUN IT results ledger.

## Capture lane

- Opener target: Monday 09:00 America/Chicago for the upcoming Saturday-through-Monday CFB window.
- Close target: T-60 seconds.
- Retry/fallback window: T-15 minutes through T-60 seconds.
- At close, capture DraftKings `h2h`, `spreads`, `totals`, plus `alternate_spreads` and `alternate_totals`.
- No post-start capture and no backfill.
- Raw market captures are append-only on the `data` branch.
- Market capture alone does **not** start the promotion clock. A genuine hash-bound `Model_P` decision row is still required.

## Known provider limitation

The current Odds API transport does not expose a verified DraftKings market-limit status. Because the frozen policy requires `book_limit_status_required=true`, the collector records `BOOK_LIMIT_STATUS_UNKNOWN` and marks those quotes **not promotion-grade** until a verified limit-status source is bound. It never fabricates a limit status.
