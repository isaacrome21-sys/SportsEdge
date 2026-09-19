# Ops unblock checklist — CFB / NFL / MLB model completion

Status date: 2026-09-19. This checklist creates no Model_P, Truth Gate, promotion, staking, or OFFICIAL authority.

## Shared paid-provider path

The Odds API last recorded production state: HTTP 401 `OUT_OF_USAGE_CREDITS` (2026-09-15 preflight `BLOCKED_NO_CREDITS`). NFL capture and any remaining MLB quotes share this keyring.

1. Confirm the live keyring in the hosted secret store. Do not commit keys.
2. Restore usage capacity or rotate only after the account-wide terminal condition is cleared. Do not keep rotating into the same 401.
3. Re-run the provider-acceptance probe. Required result: authenticated, remaining credits sufficient for the next football capture window, not merely a green workflow conclusion.
4. Keep the independent liveness observer on. Scheduler green is not evidence accrual.

## CFB reconstructed-selection attempt #1

Frozen window remains 2015–2025. Attempts consumed: 0 of 4.

1. Confirm CFBD tier, monthly quota, remaining quota, planned new calls, and 50-call retry reserve before any historical replay call.
2. Do not shrink seasons or weeks to fit leftover quota. If remaining quota cannot cover the frozen plan + reserve, stop fail-closed.
3. Reuse verified cached slices. Acquire only missing endpoint/season/endWeek identities.
4. Bind raw response SHA-256, retrieval timestamp, and provider contract into the reconstructed-selection identity.
5. Only then run the four-family evaluator once. Freeze PASS/FAIL immediately. No post-readout retune.

## NFL V2K

V2H / V2I / V2J remain rejected. V2K is research-implementation only. Attempts used: 0 of 5.

1. Keep market prices out of fit features.
2. Freeze empirical signed-key reference as `FROZEN_READY` with real source hashes before untouched readout.
3. Do not score a development attempt until the attempt ledger records the specification.
4. Props stay NO_ENGINE until a game Model_P exists.

## MLB

2026 V8 forward holdout is closed unusable (zero durable evidence). Do not backfill September 2026.

1. Keep Odds API capacity on football while NFL Week 2 confirmation is live.
2. Carry liveness + active-window mutation guards into the 2027 prospective design.
3. Catalog/runtime/settlement completeness is not promotion evidence.

## Definition of done

A sport is complete only when:

- a hash-bound fitted artifact exists,
- untouched evaluation is frozen PASS,
- Truth Gate reports exist under the frozen policy,
- contemporaneous prices and forward CLV are bound,
- OFFICIAL is emitted by the gate, not by a card formatter.
