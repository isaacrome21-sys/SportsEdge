# REGISTRY RETIREMENT RECORD — FREE_MODELS_GAME NFL spread / total draft registrations

**Status: PART OF A PREPARED FREEZE ACT — DRAFT ONLY.** This record
is carried by the NFL_ENTRY_FORM_V2 freeze-act pull request (branch
`rocky/efv2-freeze-act-20261028`, prepared Oct 28, 2026). **The
retirement recorded here takes effect only at that PR's merge, and
that merge executes only on Isaac's prospective owner authorization
recorded in chat. Until then nothing in this record is in force: on
main both registrations below remain in place, byte-identical, and
no config's status has changed.** The freeze act itself is governed
by `FREEZE_ACT_CHECKLIST.md` and recorded in `FREEZE_RECORD.md` in
this directory; the analysis this record executes is
`COLLISION_RESOLUTION_MEMO.md` (PR #2902), Option A — retirement
inside the act's own PR, sequenced **before** the act's config flip
in the same PR, so no state of main ever holds both registrations
or neither.

## What is retired

The two FREE_MODELS_GAME draft registrations that claim the
(NFL, SPREAD) and (NFL, TOTAL) keys in the forward-validation
registry (`scripts/audit_cross_sport_accuracy_readiness.py` admits
exactly one config per (sport, market) and raises
`DUPLICATE_FORWARD_MARKET_CONFIG` on a second claimant):

| File (deleted by the freeze act) | sha256 (bytes on main at the act's base) |
|---|---|
| `sportsedge/forward_validation/configs/nfl_spread.json` | `0e25ee74c4b3b56d469b5d01ec965c829be7cd39a9c785576dfa6fc234707b66` |
| `sportsedge/forward_validation/configs/nfl_total.json` | `bd18c77ff1c4854e9c7adaebd787529860d764cf04ea0b4de36ce71bf09da425` |

Both carry, on their face: `status: "DRAFT — NOT FROZEN"`,
`engine_id: "FREE_MODELS_GAME"`,
`model_version: "FREE_MODELS_GAME:LANE_A_INDEPENDENT"`, and a
`prereg_draft` pointer — no `prereg`, no `prereg_sha256`.

## The evidence (restated so the precondition is auditable from this record)

Retirement is lawful only because the incumbents are unfrozen
drafts with zero countable history. Each element:

1. **Never modified since creation.** The GitHub API commit history
   for each file contains exactly one commit — `11d168ddd`
   (Oct 20, 2026, "Forward-validation program: evaluator framework +
   35 draft preregistrations + program map"). Re-verified at this
   act's preparation on its base head `3fe1d0bde`: both histories
   still return that single commit, and both files hash to the
   sha256s in the table above.
2. **Zero rows can have counted, by their own terms.** Their draft
   preregistrations
   (`research/forward_validation_program_20261020/drafts/PREREG_NFL_SPREAD_FORWARD_V1_DRAFT.md`
   and the TOTAL twin) open: "Status: DRAFT — NOT FROZEN, NOT
   IN FORCE… **No game, row, or slate counts toward this test before
   its freeze.**" No freeze was ever recorded for either (the
   program directory holds only `PROGRAM.md` and `drafts/`), so the
   countable-row count under these registrations is zero by
   construction.
3. **No run or verdict record cites them.** The framework evaluator
   stamps every verdict record with its config's sha256
   (`sportsedge/forward_validation/core.py::evaluate_family`). A
   tree-wide search at this act's preparation finds the two sha256s
   above in exactly one file — `COLLISION_RESOLUTION_MEMO.md` in
   this directory, naming them as the collision. No verdict record
   carries either.
4. **No code loads them.** `core.py` loads a single config by
   explicit path; a tree-wide search for either filename across the
   repo's code finds no loader reference (the readiness audit's
   directory glob is the only enumeration, and it registers what
   the directory contains). The configs are evaluator
   registrations, not pricing inputs.
5. **Lane A is not a consumer.** `FREE_MODELS_GAME:LANE_A_INDEPENDENT`
   is Lane A's version string; Lane A prices from
   `artifacts/free_models.py`, which never reads these configs.
   Retiring the registrations cannot move card pricing or the
   frozen NFL team-totals §6b Lane A baseline (which pins the Lane
   A *files* by sha256 — untouched by this act).
6. **Scope is surgical.** FREE_MODELS_GAME holds eight other draft
   registrations (NFL moneyline; CFB moneyline/spread/total; MLB
   moneyline/run line/team totals/totals). Only the two NFL
   (SPREAD) and (TOTAL) registrations collide with
   NFL_ENTRY_FORM_V2. This act touches no other registration, no
   other draft, and the FREE_MODELS_GAME engine not at all.

## Why deletion, and why inside the act

The audit's status vocabulary is closed — `DRAFT … NOT FROZEN`,
`FINAL-CANDIDATE … NOT FROZEN`, `FROZEN …` — and raises
`UNKNOWN_CONFIG_STATUS` for anything else; there is no RETIRED
status the audit accepts, so an in-place tombstone is not lawful
under the code as written (memo §3, Option E rejected). Removal is
the registry's own deregistration mechanism: the audit registers
what the directory glob returns, and a file that is not in the
directory claims nothing. The governed record — this document —
carries the tombstone's information lawfully. Doing the retirement
inside the act's own PR, before the flip, means the (NFL, SPREAD)
and (NFL, TOTAL) keys pass directly from the retired drafts to the
EFV2 config: no state of main holds both registrations (duplicate)
or neither (`NO_FORWARD_TEST_CONFIG` for two priced canonical
markets).

## What is NOT touched

- The two draft preregistrations remain in
  `research/forward_validation_program_20261020/drafts/` as
  historical drafts, byte-untouched — this record, not an edit to
  the drafts, carries the supersession.
- The dated Oct 21, 2026 readiness snapshot
  (`research/cross_sport_accuracy_readiness_20261021.json`) is a
  historical artifact and is not regenerated or edited; it
  continues to describe Oct 21 state truthfully.
- Lane A pricing, the NFL team-totals clock, and every frozen
  family's terms are untouched.
- The multiple-testing k is unaffected: the retired drafts were
  never clocks and appear nowhere in the act's k = 12 table.

**Named consequence, accepted by adopting the act:** while the
EFV2 clock runs, the one-config law bars a future FREE_MODELS_GAME
NFL spread/total draft registration; reviving that test later
requires the EFV2 clock to have closed and a fresh draft —
`PROGRAM.md` §4.2 already framed these drafts as freezable-or-not
at the owner's election.

*Prepared Oct 28, 2026 as the first step of the NFL_ENTRY_FORM_V2
freeze act. Evidence re-derived at preparation on the act's base
head `3fe1d0bde` (file hashes, GitHub API histories, tree-wide
reference searches), restating `COLLISION_RESOLUTION_MEMO.md` §2.
The retirement is recorded at the act's merge; before that merge,
nothing here is in force.*
