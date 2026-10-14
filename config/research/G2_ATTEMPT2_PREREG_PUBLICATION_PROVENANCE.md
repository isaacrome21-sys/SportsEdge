# Publication provenance — G2 attempt-2 preregistration (Amendment 2; records publication)

- **Published:** 2026-10-13, on this records branch
  (`records/g2-attempt2-preregistration-20261013`), by the Muse lane at the
  owner's direction.
- **What this is:** a records publication only. It makes the frozen Amendment 2
  preregistration package retrievable from GitHub. It is not an execution
  authorization, and it changes no status.
- **Execution status: NO-GO.** G2 Attempt 2 is **unspent and unauthorized**.
  Real-data fitting and scoring are not authorized; the runner refuses
  `ATTEMPT_2_NOT_AUTHORIZED`. Nothing in this publication exercises the
  runner or accesses any holdout.
- **Owner verification gate:** the owner's independent verification of the
  freeze hashes below still precedes any execution ruling. Publication is
  not verification, and no go/no-go decision is recorded here.
- **Rule basis:** Amendment 2 APPROVED by the owner (Isaac), Oct 13, 2026
  (issue #2161): §6 governs — training-window-only σ selection is mandatory;
  the inherited §2.5 procedure is superseded for G2 Attempt 2. J1 + K3
  adopted per issue #2131. All performance thresholds unchanged.

## Published files (byte-identical to the frozen package)

| Published path | Source document | SHA-256 |
|---|---|---|
| `config/research/nfl_score_counts_g2_prereg_v2.json` | Preregistration JSON (Amendment 2) | `114b0a5d9bb1e9c8cbc6108f08ebaa0223c2e63e2e02da08aca8bfe3cb8f1ff5` |
| `config/research/G2_ATTEMPT2_PREREGISTRATION.md` | Amended `PREREGISTRATION.md` | `78e0b6a63d7fbb7c160733cdd26c63addab8ea00e2ff204d740e75ae3ab8c06f` |
| `config/research/G2_ATTEMPT2_PREREGISTRATION_v_bb35cafc.md` | Superseded preregistration state (retained draft) | `bb35cafcdc34ed2d39632ebf564af2de0879daa8e4bdc90434789aa684555a70` |
| `config/research/G2_ATTEMPT2_AMENDMENT_2.md` | Amendment 2 record | `88f3a84310030a1e4715cf5889fc92266253289d5a82ceb7ab0a769bbcd3be4a` |

## Freeze identities

- **Amended PREREGISTRATION.md — SHA-256:**
  `78e0b6a63d7fbb7c160733cdd26c63addab8ea00e2ff204d740e75ae3ab8c06f`
- **Preregistration JSON** (`config/research/nfl_score_counts_g2_prereg_v2.json`)
  — **SHA-256:** `114b0a5d9bb1e9c8cbc6108f08ebaa0223c2e63e2e02da08aca8bfe3cb8f1ff5`
- **Frozen code commit:** `2f3af2a2594effa1bbaed4137516ade8e1c15422` on branch
  `research/g2-attempt2-amendment2-20261013` (base `9f8a17cd1…`).
- **Implementation (code) patch — SHA-256:**
  `92d6d3b72529ea56e9e5a3353bd9c12b195e76205b2ab7b5972a8128150c41f6`
  (= `git diff 9f8a17cd1… ..2f3af2a2…`; re-derived and matched at publication
  time).
- **Full Amendment 2 patch — SHA-256:**
  `b11a4f852fcd10c01718b847eda44e54fec4df926b94512d549af2e989d9469c`
  (file `exports/g2_attempt2_amendment2_20261013.patch` in the Muse
  workspace exports record).

## Supersession chain (as PREREGISTRATION.md states it)

`d5096a8665bb2761cde7185a36cccd3cde4f4e3a1235894b7c64203c17f08357` →
`bb35cafcdc34ed2d39632ebf564af2de0879daa8e4bdc90434789aa684555a70` →
`78e0b6a63d7fbb7c160733cdd26c63addab8ea00e2ff204d740e75ae3ab8c06f`

- The pre-amendment state (`d5096a86…`) is the hash cited in the GitHub
  execution-hold record (issue #2131). No byte-identical copy of that state
  was retained; it rests on contemporaneous preparation records — a retained
  limitation, stated in the package itself.
- The `bb35cafc…` state is published byte-identical alongside this note. The
  current state (`78e0b6a6…`) is the amended PREREGISTRATION.md above.

## Synthetic evidence (documented in the package; not execution)

- Synthetic battery on the frozen branch tree: **49/49** (0 failures,
  0 errors), as recorded in the package's Amendment 2 implementation record;
  the CLI refusal (`ATTEMPT_2_NOT_AUTHORIZED`, exit 2) was exercised on
  synthetic inputs only. No real data was fitted or scored in the making of
  this record.

## History, stated plainly

Until this publication, the Amendment 2 package existed only locally — in
the Muse workspace package folder and in the local clone's research branch
(`research/g2-attempt2-amendment2-20261013`). It was on no remote branch, and
the preregistration JSON's path does not exist on `main`. This branch
publishes the documents byte-identical so the attempt-2 record is
retrievable; the publication is dated today and must not be read as evidence
the documents were remote at any earlier time. Byte identity is verifiable
by the SHA-256 values above.
