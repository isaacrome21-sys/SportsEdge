# FREEZE RECORD — `UFC_ML_LOWEXP_PRORECORD_V1`

**Status: THE FREEZE IS RECORDED AT MERGE OF THE FREEZE-ACT PULL REQUEST
THAT CARRIES THIS RECORD.** Before that merge nothing in this package is
in force: no clock has started and **counted rows are 0**. The freeze takes
effect only at the merge, never at a commit, push, or review. An
independent exact-head review closes on this PR's head **before** the
owner's merge records the freeze.

- **Authority:** Owner Isaac ruling, Oct 29 2026, relayed in chat: "UFC
  prereg (PR #2925): Freeze the draft so the admission audit can start.
  Counted rows stay 0." (Recorded on #2925, comment 6509459423.) Package
  prepared under the owner's "You decide" delegation (Oct 29 2026).
- **Freeze timestamp:** the merge commit's timestamp on main. None is
  asserted in advance.
- **Stacking:** this PR stacks on #2925 (branch
  `rocky/ufc-lowexp-prorecord-prereg-20261028`, head `124854b04`). The
  freeze act lands the draft package and this record together.

## Pins (sha256, computed on the bytes in this package)

| Artifact | sha256 |
|---|---|
| Frozen preregistration `PREREG_UFC_ML_LOWEXP_PRORECORD_V1.md` | `77926a934ab16fb7ad0843d8ebdaad68793611ae3a2ff504d89193a92224daa7` |
| Superseded draft `PREREG_UFC_ML_LOWEXP_PRORECORD_V1_DRAFT.md` (retained, unchanged) | `00263b29cde509bda41e540ba343accfd07e083304a5c3cfc2e8ac9c4f671429` |
| `BUILD_SEQUENCE.md` (adopted with the preregistration) | `7ff8daa825d249ef12097d41a850deaa03459178e2f29e6112ca864ca8f5fd0a` |

Every other pin is the draft package's `SPEC_HASHES.txt`, carried
unchanged: the design memo, its review, V1's record, the implementation
references and the five data files.

**Frozen text vs draft:** the two differ only in the title's "(DRAFT)",
the status paragraph, the §12 first bullet, and the closing italic line.
No statistical term, threshold, window, floor, or rule changed (verify
with `diff`).

## What the freeze does and does not do

- **Binds:** the construction (§4), universe and identity rules (§2), the
  §5 floors (BFO join ≥ 0.85, pro-record coverage ≥ 0.90), the Leg A/Leg B
  criteria, the §11.2 no-peek rule (binding from the merge onward), and the
  BUILD_SEQUENCE order.
- **Next step, per BUILD_SEQUENCE step 2:** the §7.1 pro-record source
  admission audit. A FAIL voids the construction. No build precedes it.
- **Left to later acts, as the draft states and not filled here:** the
  BestFightOdds close semantics (§7.2 admission act), and the choice of
  primary pro-record source (Tapology vs Sherdog), which the §7.1 admission
  act names.
- **Counted rows: 0.** Leg B's clock starts only when capture accrual is
  demonstrated (§7.3), not at freeze. No PLAY is created. PAPER / research
  only.

## Remaining before the merge (not faked)

- [ ] Independent review on this PR's exact head.
- [ ] Freeze-coverage matcher re-run on this head (the draft package was
      NOT GOVERNED on its 3 paths; this PR adds 2 research paths and edits
      SPEC_HASHES.txt).
- [ ] Owner merge, which is the recording act.
