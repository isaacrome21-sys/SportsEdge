# NBA team totals — governed pin-push receipt act preparation

**Status: DRAFT ACT PACKAGE / NOT EXECUTED.** Prepared 2026-10-27 CT for independent review and a future owner-authorized act. This file is documentation only: no receipt exists, no counted clock starts, and no evaluator/prereg/pin/gate byte changes are made by this PR.

## Existing exact identities on main

- Frozen prereg: `research/nba_team_totals_forward_20261022/PREREG_NBA_TEAM_TOTALS_FORWARD_V1_DRAFT.md`, SHA256 `0274e8cd248ed56a43c445c3d23e96e04eb218f4abcafb2ebe4041448ef55504` per `FREEZE_RECORD.md`. Amendments 1 and 2 remain immutable.
- Pinned evaluator: `eval_nba_team_totals_v1.py`, SHA256 `63db53129556de7a2d007020aebda9b1a5ed2ede7e4a5a0053ba6aaa2b761be9`; pin commit `37b541745154fb73985e761f7b21a7ba7a8b2381`; `EVALUATOR_PIN.md` records independent review.
- Count admission boundary: `count_gate_nba_team_totals_v1.py`, `NBA_TT_COUNT_GATE_V1_1`. `COUNT_GATE_PIN.md` pins gate module SHA256 `723cc220aa2817916d7aa62321518c6a85203d4fba374c43e05f0572f4cca3b6` and dedicated test SHA256 `40e1def77d8f9537e7963b8a20f3f318f281b5a484d81a667a4f4f7b8b87e014`.
- V1.1 #2810 prevents the public `publish_counted` receipt-path/self-hash forgery. Current gate `RECEIPT_PATH = HERE / "PIN_PUSH_RECEIPT.json"`, `RECEIPT_SHA256 = None`; thus every normal count attempt must refuse `TRUSTED_PIN_PUSH_RECEIPT_UNAVAILABLE` before evaluator invocation and without a ledger.
- `FREEZE_RECORD.md` lists nine overlapping clock identities and k=9 at the original freeze. Preserve its terms; any later multiplicity determination must follow the frozen review rule rather than silently editing the old record.

## Evidence required before preparing the governed receipt commit

1. **Independent pin-push time attestation:** Retrieve the authentic GitHub server-side push event/receipt for the pinned evaluator commit, with event ID, repository/ref, commit SHA, observed UTC timestamp, immutable raw response/archive hash and independent attester. Commit author/committer timestamps, local filesystem mtimes, and the first available API observation are **not** proof of the original push time. If the historical event cannot be authenticated, stop: do not manufacture a timestamp or backdate a receipt.
2. **Pin identity proof:** Rehash the evaluator's actual main bytes, frozen prereg and both amendments; verify exact matches with `EVALUATOR_PIN.md`, `FREEZE_RECORD.md` and the gate's embedded `PINNED_EVALUATOR_SHA256` / `PIN_COMMIT`. If bytes differ, do not proceed via a silent pin rewrite.
3. **Prospective first slate:** Name an actual future NBA slate/date that begins strictly after both the independently attested evaluator pin push and the reviewed receipt act. Confirm the first eligible `priced_at` and every entry `captured_at` are strictly after the pinned push boundary and independently authenticated by #2792. No pre-pin or backfilled row is eligible.
4. **External capture gate:** Require actual rendered DraftKings source-to-issue five-stage receipts (due/dispatch/source/ingest/durable write/delivery, quote-clock provenance, event/market/team IDs, source-byte SHA and immutable locator), fixed per-game cutoff, failures and prospective p50/p95/max/misses. The receipt act does not cure #2792 by itself.
5. **Independent review BEFORE act:** Rocky independently verifies the proposed exact commit/head, full provenance, adversarial tests, and both ruleset-23637426 required hosted checks SUCCESS. Review must close **before** the act records any new freeze/counting authority. The owner separately authorizes the first counted slate. Merge commits only; remote main SHA readback and #2447 receipt after landing.

## Exact three-file future act (DO NOT APPLY in this PR)

In a **separate** owner-authorized, independently reviewed commit, and only after items 1–5 are genuinely satisfied:

- Add `research/nba_team_totals_forward_20261022/PIN_PUSH_RECEIPT.json` with `evaluator_sha256`, `pin_commit`, `pin_push_time_utc`, `first_counted_slate`, `attester`, and `attestation_source` grounded in an immutable external receipt. Include external raw SHA/locator in the evidence record, not a made-up provider clock.
- Set `RECEIPT_SHA256` in `count_gate_nba_team_totals_v1.py` to the SHA256 of the final exact receipt bytes at the fixed canonical path; do **not** enable caller-provided `receipt_path` or `receipt_sha256` overrides.
- Update `COUNT_GATE_PIN.md` to the new gate module SHA256, with versioned provenance and review. Do not edit the frozen evaluator, prereg, amendments, historical metrics, frozen k/seed/resamples, or existing ledger rows.

## Required fail-closed acceptance probes

Before and after the future act, test the public `publish_counted` boundary: (a) missing receipt; (b) forged caller receipt with matching self-hash; (c) altered canonical receipt bytes; (d) wrong evaluator hash or pin commit; (e) missing/naive/unverified pin timestamp; (f) pre-pin `priced_at` or quote `captured_at`; (g) first-slate mismatch; (h) changed k/seed/resamples/clock IDs or extra config; (i) duplicate/partial/failed ledger write; and (j) a valid synthetic **test-only** canonical receipt. All refusals must have zero evaluator calls and zero counted-ledger writes; a synthetic pass never authorizes a real clock. Independently confirm the actual source/quote clocks and future-slate identity.

**Current decision: HOLD.** Trusted push-time source receipt and real #2792 authenticated delivery are not available in this record. No receipt was created, no code/pin altered, no counted rows or wager authority conferred. PAPER/0u.
