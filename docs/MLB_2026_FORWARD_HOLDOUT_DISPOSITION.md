# MLB 2026 forward holdout terminal disposition

Status: **FAILED_NONACCRUAL / ZERO_DURABLE_EVIDENCE / CLOSED_UNUSABLE**

This record closes the 2026 MLB forward-holdout lane without redefining the preregistered window, salvaging later dates, backfilling missing observations, or creating any Model_P, Truth Gate, promotion, staking, or OFFICIAL authority.

## Frozen window and V8 scope

- `config/mlb_replay_policy_v1.json` preregistered the untouched forward holdout as **2026-09-01 through 2026-09-27**.
- `config/mlb_v8_evidence_policy.json` made V8 forward evidence admissible beginning **2026-09-03**.
- **2026-09-11 is not a replacement endpoint.** It is the date automatic MLB acquisition was deliberately parked for Odds API budget allocation to football.

The frozen September 1-27 interval remains the declared holdout. It is unusable because qualifying V8 evidence did not accrue, not because the endpoint was retrospectively shortened.

## Durable evidence result

The durable `data` branch contained V8 runtime-status records for September 8, 9, and 10, but no durable `evidence/mlb_v8_forward` evidence directory was present during the terminal audit.

Known qualifying/targeted attempts ended:

- `status: MISSED_OR_BLOCKED`
- `capture_outcome: skipped`
- `model_outcome: failure`

This includes valid T-30 decision opportunities on September 8 and September 9. The durable promotion-evidence count for the V8 forward lane is therefore **0**.

Green scheduled workflow conclusions are not evidence of accrual. They established only that orchestration ran.

## Root cause and scope

The September 8 exact-run artifact establishes the first hard root cause in the failed production chain:

- The Odds API returned **HTTP 401 `OUT_OF_USAGE_CREDITS`**.
- `odds_rows_fetched` remained `0`.
- `model_priced` remained `0`.
- pipeline health was `BROKEN`.

Classification: **SHARED_INFRASTRUCTURE**.

The failure occurred in the shared market-data/provider-quota path upstream of MLB-specific lineup requirements or successful Model_P production. NFL production capture also depends on The Odds API credential/provider path, so this diagnosis is an immediate cross-sport operational risk rather than only a 2027 MLB bug report.

This does not prove that every September 8-10 failure had the identical root cause. It is sufficient to prove that at least one valid decision opportunity failed on shared provider infrastructure and that the 2026 lane accumulated zero durable V8 evidence units.

## September 11 parking decision

The September 11 WS-CREDIT decision parked scheduled MLB V8 acquisition to reserve paid-provider capacity for football. That action terminated an already non-accruing evidence lane; it did not interrupt a functioning sample.

The original audit phrase `Evidence-unit impact: NONE` was accurate only with respect to the *definition* of an evidence unit. It was not an adequate description of evidence acquisition during an active preregistered window. The corrected distinction is:

- **Evidence-definition impact: NONE.**
- **Evidence-accrual opportunity: TERMINATED for the active MLB forward lane.**

## 2026 decision

Do not resume or salvage the MLB 2026 forward holdout.

- No backfill.
- No retrospective restart rule.
- No discontinuous September sample relabeled as the original untouched holdout.
- Keep scarce Odds API capacity allocated to the live football evidence lanes.
- Carry the shared-provider failure and liveness controls into the 2027 MLB prospective design.

## Required controls learned from this failure

### Active-window mutation guard

For every ACTIVE preregistered evidence window, parking, disabling, removing schedule authority, materially reducing cadence, removing the declared provider path, or removing persistence requires an explicit recorded window disposition before the mutation may merge.

### Active-window liveness guard

Workflow success is not evidence liveness. A separate observer must fail loudly when a due acquisition opportunity does not produce durable, contract-valid output. For the NFL 2026 confirmation archive this is implemented independently from the capture workflow and reads durable repository state rather than the capture workflow conclusion.

A missing or blocked due window remains a failure requiring attention even when a durable `MISSED_OR_BLOCKED` marker correctly preserves the no-backfill record.
