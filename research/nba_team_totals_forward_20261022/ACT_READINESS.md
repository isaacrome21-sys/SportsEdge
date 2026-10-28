# ACT READINESS — NBA Team Totals Count-Gate Type Guards (2026-10-28)

This PR prepares the **guard half** of the future governed pin-push
receipt act for the NBA Team Totals Forward Test V1 count gate. It does
**not** execute the act: no receipt is installed, `RECEIPT_SHA256`
remains `None` in the gate module, and every counted publication still
refuses with `TRUSTED_PIN_PUSH_RECEIPT_UNAVAILABLE`. The forward clock
remains on HOLD.

## The act's four files, and what this PR does to each

The receipt act lands in ONE reviewed commit containing four files:

1. **`PIN_PUSH_RECEIPT.json`** (new, beside the gate) — **NOT in this
   PR.** The receipt itself is the act.
2. **Gate module `RECEIPT_SHA256` set** to that file's sha256 —
   **NOT in this PR.** The constant stays `None`; the gate stays
   fail-closed.
3. **`COUNT_GATE_PIN.md` update** — **prepared in this PR** for the
   guard content: gate version `NBA_TT_COUNT_GATE_V1_2` and the guarded
   module's sha256 are attested there now. Turnkey note: step (2)
   changes the module's bytes again, so the act commit must refresh
   the pin's module sha256 to the act-final module bytes, exactly as
   the pin's receipt-installation procedure already prescribes.
4. **The guarded gate module** (`count_gate_nba_team_totals_v1.py`) —
   **prepared in this PR.** Strict boundary typing (V1.2 correction,
   recorded in `COUNT_GATE_PIN.md`): ISO slate strings compared as
   parsed dates, exact-type caller config, named `GATE_TYPE_INVALID`
   refusals for wrong-typed records/collections, non-object receipts
   refused as `PIN_PUSH_RECEIPT_MALFORMED`. Regression coverage:
   `test_count_gate_nba_team_totals_v1_type_guards.py`. The pinned
   evaluator (`eval_nba_team_totals_v1.py`, sha256
   `63db53129556de7a2d007020aebda9b1a5ed2ede7e4a5a0053ba6aaa2b761be9`)
   is **not** modified by this PR; its pin remains valid.

With (3) and (4) landed, the act itself is reduced to its governed
core: issue the attested receipt (1) and set the pin (2) plus the
sha refresh under (3), in one reviewed commit.

## Blockers that remain before the act may execute

- **Independently attested pin-push time receipt.** The receipt's
  `pin_push_time_utc` must be the independently attested GitHub
  server-side push time of evaluator pin commit
  `37b541745154fb73985e761f7b21a7ba7a8b2381`. Commit author/committer
  timestamps are NOT proof. If that historical event cannot be
  authenticated, the act stops — this is the adjudication of record on
  PR #2853, unchanged by this PR.
- **#2792 authenticated delivery receipts.** Rendered-browser delivery
  acceptance remains unproven program-wide; the act's package requires
  the real receipts, not lane reports.

## Not changed by this PR

No receipt file; no `RECEIPT_SHA256` value; no evaluator bytes; no k,
seed, resamples, clock identities, or first counted slate; no counted
rows, metrics, or verdicts. PAPER / 0u. Note for the act executor:
`docs/ops/NBA_TEAM_TOTALS_PIN_PUSH_GOVERNED_ACT_PREP_20261027.md`
quotes the superseded V1.1 gate module sha256 as its state of record;
for act purposes the gate's identity is the one attested in the
updated `COUNT_GATE_PIN.md`.
