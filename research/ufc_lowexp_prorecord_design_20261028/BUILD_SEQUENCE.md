# BUILD SEQUENCE — `UFC_ML_LOWEXP_PRORECORD_V1`

**Status: planning note beside a DRAFT preregistration**
(`PREREG_UFC_ML_LOWEXP_PRORECORD_V1_DRAFT.md`). This note fixes the
order of the work that follows adoption. **Nothing in this PR executes
any step of it**: no engine is built, no audit is run, no screen is
run, no clock starts, and counted rows remain 0.

1. **Owner adoption + freeze act** on the preregistration draft. Any
   term changes are made on the record *before* the act; after it, a
   change is a new version judged on later data. The §11.2 no-peek
   rule binds from the freeze act onward.
2. **§7.1 pro-record source admission audit** → an admission record
   naming exactly one primary source (panel reconstruction, coverage
   table, collision enumeration, documentation-timing measurement).
   FAIL → the construction is VOID; the sequence stops. No build of
   any kind precedes this step.
3. **§7.2 BestFightOdds admission + join audit** → Leg A exists, or
   Leg A is void. If void, proceeding on Leg B alone requires an
   explicit owner ruling on the record (zero historical evidence).
   This step may run in parallel with step 2; its join may not be
   computed before step 1 (no-peek rule 2).
4. **Build** — feature reconstruction per §4/§5 from admitted sources
   only; the §7.4 segment count check reported in the build record
   (degenerate counts stop the build); the frozen artifact and its
   implementation pins recorded.
5. **One declared Leg A screen run** (§8) — exactly one look over the
   whole judged window, with the §11.2 attestation and access log in
   the screen record. Outcome recorded as PASS, FAILED_SCREEN, or
   INSUFFICIENT_N. FAIL retires the construction on the record.
6. **Forward stage (only on a Leg A PASS, which earns eligibility and
   nothing more)** — owner decision on the forward preregistration;
   §7.3 DK capture-accrual demonstration; Leg B forward run under
   §9–§10. If Leg A was voided at step 3 or under §11.2 rule 5, this
   step exists only via the explicit owner ruling named there.

*Prepared Oct 28, 2026, beside the draft preregistration. This
sequence is itself part of the draft package: adopting the
preregistration adopts the order.*
