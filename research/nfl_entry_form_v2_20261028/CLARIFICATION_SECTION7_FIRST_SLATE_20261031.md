# CLARIFICATION — NFL_ENTRY_FORM_V2: PREREG_FINAL §4/§7, the §7 landing check and the identity of the first counted slate

**Status: CLARIFICATION OF FROZEN TEXT — NOT AN AMENDMENT.** This
memo records a prereg-reading ruling on the frozen
`PREREG_FINAL.md` (sha256
`cfc7047caa898e624c737d3fbf4fd35e2abe8dca638c7b312c4f193f53e098ea`,
unchanged by this memo — no frozen text is edited). It changes no
term, threshold, pin, or gate. Its status is the same as the
Oct 22, 2026 minimum-gate clarification
(`CLARIFICATION_MINIMUM_GATE_40_GAMES_20261022.md`, filed in the
Part 2 / Part 2B / NBA props prereg directories): a reading of the
frozen text as written, recorded where the family reads it.
Amendments after the freeze remain new versions with their own
preregistrations, scored forward only (PREREG_FINAL §9).

**Ruling:** Rocky (prereg-reading authority), Oct 31, 2026 —
recorded prospectively, before the Sunday Nov 1, 2026 lane
writes, and **recorded for the owner's override**: an owner
ruling contrary to this memo supersedes it.

## 1. The question

PREREG_FINAL §4 requires the first eligible slate's entry
snapshots to post strictly after the freeze timestamp **and**
after the §7 landing check passes. The landing check is itself a
live demonstration that consumes a current slate's lane
snapshots. Two readings were open:

- **Reading A:** the demonstration consumes a non-counted slate
  before the first counted one; the demonstration slate does not
  count.
- **Reading B:** demonstrate NON_COUNTED on the Nov 1 slate's
  snapshots Sunday morning, verify the run-record fields, then
  price the same slate counted.

## 2. The governing texts (verbatim)

PREREG_FINAL §4:

> - **First eligible slate:** the first Sunday slate with ≥ 8
>   captured games whose entry snapshots all post strictly after
>   the freeze timestamp **and** after the §7 landing check
>   passes. The freeze record names the slate by date if known.

PREREG_FINAL §7, item 8:

> 8. **First eligible slate** per §4, named by date or by rule,
>    plus the landing check (full path capture → price → record →
>    grade proven on a non-counted slate) scheduled and verified
>    **before** that slate.

PREREG_FINAL §14:

> The build's landing check (2025 Week 10, NON_COUNTED, on file
> in this directory) proves the capture → price → record → grade
> path; the freeze act's checklist re-verifies the live pricing
> path on a non-counted slate before the first eligible slate.

FREEZE_ACT_CHECKLIST.md:

> - [ ] **Live pricing path proven before the first eligible
>   slate** … before the first eligible slate the capture → price
>   → record path must be demonstrated on a current, non-counted
>   slate from live lane snapshots, and the run-record fields the
>   adapter needs (entry snapshot, personnel state, Lane A
>   emissions per §5.6a) verified present per row.

FREEZE_RECORD.md, OPEN ITEMS:

> - [ ] **Live pricing path demonstration (OPEN — due after
>   merge, before the first eligible slate).** … the capture →
>   price → record path must be demonstrated on a current,
>   non-counted slate from live lane snapshots, with the
>   run-record fields the adapter needs (entry snapshot,
>   personnel state, Lane A emissions per §5.6a) verified present
>   per row, **before** the first eligible slate.

Facts of the freeze: NFL_ENTRY_FORM_V2 froze at the merge of
PR #2919 on Oct 31, 2026 — freeze instant
**2026-10-31T07:21:50Z** (merge commit `201b3b98f`). The only
candidate demonstration slate is Sunday Nov 1, 2026: exactly 8
NFL games are registered with the lane for that slate (all
12:00 CST), and their entry snapshots — the T-1H writes under
the lane's two-write cadence — post Sunday Nov 1
(10:30–11:00 CT), strictly after the freeze instant
(readiness analysis: `S7_READINESS.md` in Rocky's freeze
workspace, Oct 31, 2026).

## 3. The ruling — READING A governs

**A slate counts toward this test only if every one of its
entry snapshots posts strictly after the §7 landing check has
passed.** The landing check consumes a slate's live snapshots;
the slate that supplies the demonstration therefore cannot be
the slate that counts. This is §4's plain order, and §7.8, §14,
the checklist, and the freeze record all describe the
demonstration slate the same way: a **non-counted** slate that
precedes the first eligible slate.

**Reading B is rejected as unexecutable under the text.** A
slate's entry snapshots are its T-1H writes under the lane's
two-write cadence; they cannot be re-posted after the check
passes. Counting Nov 1 on snapshots that posted before the
check passed would require reading §4's "post strictly after …
the §7 landing check passes" as "priced after the check
passes" — a different sentence from the one frozen.

## 4. Consequences, by name

- **Sunday Nov 1, 2026 is the NON_COUNTED demonstration slate.**
  Its rows are priced NON_COUNTED by the pinned construction
  for the §7 demonstration only; no §5/§6 metric is computed on
  them, and they never count (no backfill).
- **The first counted EFV2 slate is Sunday Nov 8, 2026**,
  provided it independently meets §4: ≥ 8 captured games whose
  entry snapshots all post strictly after the freeze timestamp
  and after the §7 landing check passes. Once the Nov 1
  demonstration passes, Nov 8's snapshots satisfy the
  after-the-check condition by construction (they post Nov 8).
- **If the Nov 1 demonstration fails or cannot run**, no slate
  counts until a later Sunday's demonstration passes — and
  that demonstration slate likewise does not count; the first
  counted slate is the first §4-qualifying Sunday after it.

## 5. The demonstration's proof obligations (§7)

The demonstration run record files **in this directory**
(`research/nfl_entry_form_v2_20261028/`), closing the
FREEZE_RECORD open item by reference. Per row it must verify
present:

- **(a) the entry snapshot** — `entry_line`, both
  `entry_prices`, and `entry_captured_at` (the [NFL LINES]
  issue's Captured timestamp, verbatim, posting strictly after
  the freeze instant);
- **(b) the personnel state at pricing time**, per §7.7(c) —
  the personnel-state source and the snapshot-into-record rule
  (starter-knowledge state and starter identity recorded in the
  row's features at pricing time, never backfilled from post-hoc
  records);
- **(c) Lane A emissions per §5.6a** — repo-root
  `free_models.py` at the freeze commit, run on identical
  point-in-time inputs, its projections recorded per game
  beside the construction's.

*Clarification recorded Oct 31, 2026. The frozen texts stand as
written; this memo is their reading, not their revision.*
