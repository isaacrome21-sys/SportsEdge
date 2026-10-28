# COUNT GATE PIN — NBA Team Totals Forward Test V1.2 (2026-10-28)

Security repair of the V1 publication gate after the Oct 27 #2504 landing.
No frozen text is edited. The evaluator pin
(`EVALUATOR_PIN.md`) is unchanged: the evaluator's bytes remain the
pinned ones, and count admission lives here, outside the evaluator.

- **Gate version:** `NBA_TT_COUNT_GATE_V1_2`
- **Path:** `research/nba_team_totals_forward_20261022/count_gate_nba_team_totals_v1.py`
- **Gate module sha256:** `69d30c2d97ea6aa8b32d8d6c2fe24eea3b64ee52bd10f4f7d96e5227ff78e400`
- **Gate tests:** `research/nba_team_totals_forward_20261022/test_count_gate_nba_team_totals_v1.py`
  sha256 `40e1def77d8f9537e7963b8a20f3f318f281b5a484d81a667a4f4f7b8b87e014`;
  `research/nba_team_totals_forward_20261022/test_count_gate_nba_team_totals_v1_type_guards.py`
  sha256 `02263100ca63ca232199e09d3504095c2431cdb68d328824a8f98deae1228ed7`
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


## V1.1 security correction (2026-10-27; no freeze act)

The V1 publication gate merged at `e432b3573515bccaeb526ccf2480156c7348c5fa`
with module sha256 `46a979fc33163fe0af29ccba519cb09a813453114c9bbddeab9a76f48243f40c`.
Its public `publish_counted` parameters `receipt_path` and
`receipt_sha256` let a caller supply BOTH a forged backdated receipt and
the matching caller-computed digest, bypassing the intended absence of any
installed trusted pin-push receipt.

V1.1 retains the legacy keywords **only to reject them by name** with
`CALLER_RECEIPT_OVERRIDE_FORBIDDEN`, before evaluator invocation or ledger
writes. The sole receipt lookup is the module's internally configured
`RECEIPT_PATH` and `RECEIPT_SHA256`; the latter remains `None` so
all real counted publication attempts still fail closed with
`TRUSTED_PIN_PUSH_RECEIPT_UNAVAILABLE`. Tests use a synthetic in-process
module-constant fixture to probe *future* governed receipt logic; this is
not an installed production receipt or owner freeze authorization.
The adversarial test sends a multi-slate synthetic fully stamped cohort with a forged
early receipt and its **matching self-hash** through the public function,
asserting named refusal, zero calls to the scoring function and no ledger.

The original evaluator remains pinned byte-for-byte as in EVALUATOR_PIN.md;
this amendment
changes only publication admission and its dedicated test pin. No k, seed,
resamples, clock identities, historical results, or first counted slate change.

## V1.2 type-guard correction (2026-10-28; no freeze act)

The V1.1 gate (module sha256
`723cc220aa2817916d7aa62321518c6a85203d4fba374c43e05f0572f4cca3b6`) typed its
boundary by coercion. An adversarial pass reproduced, under a simulated
reviewed pin: (1) a row whose `slate_date` was the **int** `20261020` — a
pre-pin slate — passed the gate's pre-pin comparison, because
`str(20261020)` sorts lexicographically *after* the ISO first counted
slate; every gate-checked timestamp was forged post-pin, the gate
published, and the row was silently downgraded to a per-row evaluator
refusal, defeating the gate's contract that one pre-pin row refuses the
whole publication; (2) caller config values were checked by equality
alone, so float twins of the frozen ints (`k = 9.0`, `seed =
20261022.0`, `resamples = 10000.0`) were accepted for the evaluator to
`int()`-coerce; (3) a non-mapping row or quote element, and (4) a
receipt file holding valid JSON of the wrong type, escaped as raw
`AttributeError`s instead of named refusals; (5) the collections the
gate forwards to the evaluator were unvalidated, so wrong-typed
containers crashed inside the pinned evaluator.

V1.2 makes the boundary strict, in the gate module only: a slate
identity must be an ISO `YYYY-MM-DD` string and is compared as a parsed
date; caller config must repeat the frozen record in type as well as
value (bool and numeric-string counts refuse); every consumed or
forwarded record/collection must carry its contracted type. Wrong-typed
input refuses by name — `GATE_TYPE_INVALID`, or the pre-existing named
code for its site (`FROZEN_EVALUATION_CONFIG_UNAUTHORIZED`,
`PIN_PUSH_RECEIPT_MALFORMED`) — before the evaluator is invoked, and
the well-typed pre-pin case still refuses as `COUNTED_ROW_PRE_PIN`.
Behavior for well-typed inputs is unchanged, refusal precedence is
unchanged, and regression tests reproduce each defect shape
(`test_count_gate_nba_team_totals_v1_type_guards.py`).

**No receipt is installed by this correction:** `RECEIPT_SHA256`
remains `None`, no `PIN_PUSH_RECEIPT.json` exists, and every counted
publication still refuses with `TRUSTED_PIN_PUSH_RECEIPT_UNAVAILABLE`.
The evaluator remains pinned byte-for-byte as in EVALUATOR_PIN.md. No
k, seed, resamples, clock identities, historical results, or first
counted slate change. See `ACT_READINESS.md` beside this file for how
this correction composes with the future governed receipt act.
