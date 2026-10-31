# AMENDMENT 3 — ADOPTION RECORD (CBB FIRST-HALF LINES: 1H spread / 1H total)

**Date:** 2026-10-31 · **Act:** owner adoption ·
**Status after this record:** Amendment 3 is **ADOPTED**,
with **ADOPTION-REVIEW FLAG 1 settled on READING A**. The CBB
first-half family remains **DESIGN ONLY — NOT FROZEN**;
nothing counts.

## The ruling

On Oct 31, 2026 (~01:50 CT), Rocky presented Isaac with his
recommendations on the outstanding owner-act queue, including:
adopt CBB 1H Amendment 3 (PR #2913) with Flag 1 settled on
**Reading A** — the strictly-prior actual 1H means reading,
the only point-in-time-safe construction of the two the
amendment carries. Isaac answered in chat: **"Do it."** That
answer is the owner's adoption act for this amendment, on the
terms recommended. This record is that act and its reasons.
Isaac can reverse any part of this adoption with a word, and
reversal is a new record, not an edit of this one.

## What is adopted — the exact text

Amendment 3 as landed by PR #2913 (head
`279cfc222e42639edc2239f9bfff39b3f8ff67ab`, merged to main as
`be8d19a1ebbbd3bea74f52eae68056bde261d709`, Oct 29, 2026),
adopted **as written** — no term altered, added, or removed
by this act:

- `AMENDMENT_3_DRAFT.md` — sha256
  `b284443fe154e57418425c12209a0cc99e3e7a74100a6eb2529077e9961127e0`

Per the amendment's §9, gaps **G-1H-1 through G-1H-6** in
§2 of the 1H design (`CBB_TEAM_TOTALS_1H_DESIGN.md`) stand
supplied by the amendment. The design's text is never edited;
the amendment supersedes by reference. The supplied
machinery, in summary (the amendment text governs, not this
summary):

- **G-1H-1 (§1):** verdict rule for both 1H legs — the parent
  §3 bar imported (CI upper bound < 0, FAILED_SCREEN
  recording).
- **G-1H-2 (§2):** the naive half-share climatology baseline
  constructed — see Flag 1 below.
- **G-1H-3 (§3):** the first-half share estimator — ratio of
  sums over team-games, `s(S) = Σ 1H team points ÷ Σ full-game
  team points` over the strictly-prior fitting window.
- **G-1H-4 (§4):** the scored-season set — the first pinned
  season is fit-only — under the strictly-prior fitting rule.
- **G-1H-5 (§5):** inference — season-block bootstrap,
  **10,000 resamples, seed 20261028**, percentile 95%.
- **G-1H-6 (§6):** fixture universe — the parent screens'
  three-way-agreed universe intersected with the Method-A
  PBP final-agreement gate; the fitting universe likewise.

## Flag 1 — SETTLED by this act

The amendment's §9 requires the adoption act to confirm
ADOPTION-REVIEW FLAG 1 **by name**; an adoption silent on the
flag would leave G-1H-2 unsupplied. **Settled: READING A —
climatology of the 1H quantities themselves**, in the
amendment's own words (§2):

> The baseline forecast for a scored fixture is the
> **strictly-prior league mean of the actual 1H quantity**:
> prior seasons' mean actual 1H total for the total leg,
> prior seasons' mean actual 1H margin for the margin leg,
> fitted walk-forward per scored season on the §6 fitting
> universe (Method-A gated fixtures of the composed universe,
> seasons strictly before the scored season).

Reading B — the naive full-game expectation scaled by a
climatological share — is **not** adopted. Under the
amendment's own disclosure, Reading B's climatological share
and the candidate's fitted share are the same number in any
scored season, so the fitted share itself would never be
what is graded; Reading A tests the whole candidate against
raw first-half league averages and is the point-in-time-safe
reading. Under the settled reading, no share is estimated
for the baseline at all: "half-share" describes the
quantities (first halves).

## What this act does NOT do

- It **freezes nothing, counts nothing, and runs nothing**:
  no clock starts, no freeze act is effected, and no screen
  attempt is run by this adoption. `verified_play` remains
  false; PAPER / 0u throughout.
- Screen **attempt 1 stands as recorded** (PR #2911:
  NOT_EXECUTABLE — `SCREEN_SPEC_INCOMPLETE_1H`). The family
  remains **NOT_EXECUTABLE** on that record until a
  subsequent attempt runs under the completed spec, on its
  own record, through the family's own gates (the
  amendment's §9 contemplates that run as attempt 2; this
  act does not schedule or authorize it), and the family's
  freeze path remains a separate prospective act on its own
  checklist, untouched by this adoption.
- The named data prerequisite stands as admitted and is
  untouched by this act: hoopR play-by-play pinned full-tuple
  with schema verification (PR #2901), **Method A** halftime
  derivation admitted, the final-agreement consumer gate
  binding.
- It alters **no existing term** of the 1H design or of the
  parent design, and no term of the amendment itself
  (adoption as written, per the ruling above). If any term
  of the amendment is read to conflict with the designs as
  written, the designs govern, per the amendment's §9.
- It does not effect any other pending owner act (the CBB
  efficiency / team-totals freeze acts, EFV2 freeze, NFL
  period freeze, PGA G-PGA-2 pin admission, UFC prereg —
  all separate).

## Verification (this PR)

- The adopted text's sha256 above was computed from the file
  as it stands on main (`975305ce3ae36746ff3d104aaff797ecf3e598cd`)
  at the time of this act — the same bytes PR #2913 merged.
- Freeze-coverage: the repo matcher
  (`scripts/reconcile_freeze_deltas.py::_covered_change` over
  every bundle in `config/freeze_reconciliation_registry_v1.json`)
  reports **NONE** for this record's path — the act touches no
  freeze-governed path, no code, no config, and no frozen
  text; it adds this one document.
- Dependency-surface gate: `pyproject.toml`
  `dependency-groups.dev` set equals `requirements-test.txt`
  exactly (11 = 11) on the base head; this act touches
  neither manifest.
- Consumption: nothing in the repo consumes adoption records
  programmatically — no registry, index, or code path
  references `AMENDMENT_2_ADOPTION_RECORD.md` (verified by
  full-tree search at this act's base head). Adoption is
  effective by the recorded act and its merge, exactly as
  Amendment 2's was; no companion file changes are required.
