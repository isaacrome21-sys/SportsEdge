# G2 Attempt 2 — Amendment 2 record

**Ruling (owner, Isaac, Oct 13, 2026): APPROVED — Amendment 2.** "§6
governs. Training-window-only σ selection is mandatory. I accept the
audit's findings and the proposed resolution. The inherited §2.5 procedure
is superseded for G2 Attempt 2." Amendment 2 preparation, the bounded σ
correction, synthetic regression testing, and derivation of the
machine-readable preregistration JSON are authorized. Real-data fitting
and scoring are **not** authorized; execution remains **NO-GO**; attempt 2
remains **unspent**.

## Identity chain (PREREGISTRATION.md states)

| State | SHA-256 |
|---|---|
| Pre-amendment (as first prepared; cited in the GitHub execution-hold record, issue #2131) | `d5096a8665bb2761cde7185a36cccd3cde4f4e3a1235894b7c64203c17f08357` |
| Amendment 1 (owner NO-GO ruling, issue #2131) — retained byte-for-byte as `PREREGISTRATION_v_bb35cafc.md` | `bb35cafcdc34ed2d39632ebf564af2de0879daa8e4bdc90434789aa684555a70` |
| **Amendment 2 (this amendment) — current `PREREGISTRATION.md`** | **`78e0b6a63d7fbb7c160733cdd26c63addab8ea00e2ff204d740e75ae3ab8c06f`** |

**Retained limitation (explicit, per the ruling):** the pre-amendment
bytes were edited in place when Amendment 1 was applied and no separate
copy was retained, so `d5096a86…` rests on contemporaneous preparation
records. `bb35cafc…` is re-hashable from the retained copy above and was
independently verified by the owner and by the audit. The Amendment-1
state was copied byte-for-byte **before** Amendment 2 was applied, so this
amendment does not repeat the in-place-overwrite defect.

## The five change sites (and no others)

Verified by diff against the retained Amendment-1 copy: exactly seven
diff hunks, mapping to these five sites; everything else in the document
is byte-identical.

1. **§1 governance header** — Amendment 2 record added: supersession
   history with the retained limitation; §6 governs σ selection;
   freeze-chronology correction; attempt-consumption reconciliation; and
   the statement that Amendment 2 changes no gate threshold, no fold
   structure, no grid (the σ grid is unchanged — only its selection
   *placement* moves), no K3 term, and no budget term.
2. **§2.5** — heritage pooled σ-selection placement replaced with nested
   expanding-window selection inside each outer fold's training window
   (inner validation season = each training season after the first; inner
   models fitted on seasons strictly before the inner validation season,
   at the fold's selected α values; residual-product MSE in attempt-1
   form, pooled across inner folds; grid {0.0, 0.1, 0.2, 0.3} and
   smaller-σ tie-break unchanged; outer validation outcomes must never
   influence σ; a training window that cannot form an inner fold fails
   closed as a pre-scoring NOT_RUN). The heritage procedure is recorded
   as attempt 1's historical procedure, superseded for attempt 2.
3. **§1 freeze discipline + §8 checklist** — chronology corrected to the
   actual sequence: markdown package → owner-approved implementation +
   synthetic testing (Oct 13, 2026 ruling) → machine-readable JSON derived
   and frozen **before any real-data fitting or scoring**, binding the
   implementation's verified commit SHA and patch SHA-256. No step is
   backdated; any code change after the JSON freeze is a new identity
   requiring a new ruling.
4. **§4.5 + §7** — attempt-consumption reconciliation: a violation (or
   any contamination) discovered **after** a completed scored run voids
   the result (recorded `VOID` in the ledger) but the attempt **counts as
   consumed** — voiding never refunds budget and no re-run under
   attempt 2 is permitted; discovery **before** scoring aborts as
   NOT_RUN (not consumed), disposition recorded in the ledger.
5. **§9 provenance table** — the σ row now cites the amended selection
   rule (grid + statistic form remain traced to attempt-1 preregistration
   L197; the placement is Amendment 2).

## What Amendment 2 does not do

No gate threshold, fold, grid, K3 term, or budget term changes. It does
not authorize execution, fitting, or scoring on real data, and it does not
consume attempt 2. Per the ruling, the original implementation identities
(`dbb5f172b`, patch `bf0c0de4…`) remain the original tested identities —
not the final executable identities; the bounded σ correction produces
new identities, recorded in `AMENDMENT_2_IMPLEMENTATION.md`, and the
preregistration JSON binds those new verified identities.
