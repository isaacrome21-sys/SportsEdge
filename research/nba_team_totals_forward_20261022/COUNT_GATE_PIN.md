# COUNT GATE PIN — NBA Team Totals Forward Test V1 (2026-10-26)

New file. No frozen text is edited. The evaluator pin
(`EVALUATOR_PIN.md`) is unchanged: the evaluator's bytes remain the
pinned ones, and count admission lives here, outside the evaluator.

- **Gate version:** `NBA_TT_COUNT_GATE_V1`
- **Path:** `research/nba_team_totals_forward_20261022/count_gate_nba_team_totals_v1.py`
- **Gate module sha256:** `46a979fc33163fe0af29ccba519cb09a813453114c9bbddeab9a76f48243f40c`
- **Gate tests:** `research/nba_team_totals_forward_20261022/test_count_gate_nba_team_totals_v1.py`
  sha256 `98be034f50743a62d52ccdc4ea0c886b147415778eeaab1fac37fba14ce86a88`
- **Admits evaluator:** `eval_nba_team_totals_v1.py` sha256
  `63db53129556de7a2d007020aebda9b1a5ed2ede7e4a5a0053ba6aaa2b761be9`
  (pin commit `37b541745154fb73985e761f7b21a7ba7a8b2381`), verified by
  the gate from the loaded module's actual bytes on every call.

## Counted-publication rule

`publish_counted` in the gate module is the mandatory forward-ledger
write boundary for this forward test: every counted row, metric, and
verdict is published only through it. The gate derives the evaluation
config itself (frozen k / seed / resamples from the evaluator's frozen
constants; the nine clock identities recorded in `FREEZE_RECORD.md`;
the first counted slate named by the receipt), refuses any caller
config deviation by name, requires every submitted row's `priced_at`
and every entry quote's `captured_at` to be strictly after the
receipt's pin-push time, and appends exactly one record per admitted
publication to `forward_ledger_nba_team_totals_v1.jsonl`. On any
refusal it raises a named `CountAdmissionRefused`, never invokes the
evaluator, and writes nothing.

## Receipt status: NONE INSTALLED — gate fails closed

No trusted pin-push receipt has been issued under governance, so the
gate module pins `RECEIPT_SHA256 = None` and every counted publication
is refused with `TRUSTED_PIN_PUSH_RECEIPT_UNAVAILABLE`. Installing a
receipt is a governed act, done in ONE reviewed commit that together:
(1) adds `PIN_PUSH_RECEIPT.json` beside the gate (fields:
`evaluator_sha256`, `pin_commit`, `pin_push_time_utc` — the
independently attested GitHub push time of the evaluator pin commit,
never a commit author/committer timestamp — `first_counted_slate`,
attester and attestation source); (2) sets the gate module's
`RECEIPT_SHA256` to that file's sha256; (3) updates this pin's gate
module sha256. Until then the forward clock remains on HOLD:
no counted rows, no metrics, no verdict. PAPER / 0u.
