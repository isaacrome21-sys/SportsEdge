# Card Status Rules

Venue support gets a price. Promotion evidence decides whether that price may be bet. These are separate checks and are never merged.

## Row status, in order

1. **NO_ENGINE** — no probability engine exists for the market. No data request can unlock it.
2. **BLOCKED** — Model_P is missing, a hard data/venue/provenance blocker exists, or a promoted market is missing its frozen edge floor.
3. **TRIAL** — Model_P exists, a real offered price/edge exists, there is no hard blocker, the market is not promoted, and the model edge is positive. TRIAL is paper-only and exists to collect CLV/closing-line evidence.
4. **PASS** — the market is promoted, a frozen floor exists, and the model edge is below that floor.
5. **OFFICIAL** — the market is promoted, all gates pass, and the edge meets or exceeds the frozen floor.

Confidence, stake, and units appear only on OFFICIAL rows. TRIAL rows may show Model_P, fair odds, offered price, edge, and later CLV/close, but never a real stake. A context lean is a separate field and never changes a row's status.

A suggested evidence target is roughly 200 paper observations per market before considering promotion. That target is evidence guidance, not an automatic promotion rule; promotion still requires the frozen Truth Gate criteria.

Retracted cards are kept in the RUN IT ledger as process-correctness failures, with the time issued and the time retracted.

Code: `sportsedge/core/card_status.py`. Venue: `sportsedge/sports/nfl/venue_contract.py` with `config/nfl_venue_policy_v1.json`.

## Paste into the ChatGPT HYBRID instructions

```
CARD STATUS RULES (mandatory)
- NO_ENGINE: no engine exists for the market. Never ask for data to unlock it.
- BLOCKED: Model_P missing, a hard data/venue/provenance blocker exists, or a promoted market lacks a frozen edge floor. List every reason.
- TRIAL: real Model_P + real offered price/edge + no hard blocker + not promoted + positive model edge. PAPER ONLY.
- PASS: only if Model_P exists AND market is promoted AND a frozen floor exists AND edge < floor.
- OFFICIAL: all gates pass and edge >= floor.
- Confidence, stake, or units only on OFFICIAL rows. Never on BLOCKED, TRIAL, PASS, or NO_ENGINE.
- TRIAL may show Model_P, fair odds, offered price, edge, and CLV tracking; it never authorizes a wager.
- A context lean is its own line and never changes status or adds confidence.
- Never write PASS or TRIAL for a market the model did not actually price.
- If a card breaks these rules, retract it and log the retraction; do not delete it.
```
