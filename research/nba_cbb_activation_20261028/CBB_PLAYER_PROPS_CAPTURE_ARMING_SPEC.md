# CAPTURE-ARMING SPEC — CBB Player Props

**Status: CAPTURE-ARMED (SPEC) — CONSTRUCTION: NO_CONSTRUCTION —
HISTORICAL DATA: NO_DATA — NO CLOCK, NO COUNTING, NO PRICES ISSUE FROM
THIS SPEC.** Date: 2026-10-28. This family's activation problem is not
a model problem: no historical CBB prop lines exist anywhere admitted
(gap G1/G5), so there is nothing to screen against. The only asset this
family can accumulate is a **forward capture archive**, and this spec
arms that accumulation so the archive is born admissible.

Composition note: PR #2350 claims CBB player-stat foundations and
PR #2280 the DK captured-market evidence contract (both unvalidated);
this spec composes with them and reimplements neither.

## 1. What capture does, starting with the first slate

The capture scope already exists: draft PR #2820 mandates the
player-props menu be inspected on **every** captured game, with eight
recordable categories (points, rebounds, assists, threes, PRA,
points+rebounds, points+assists, rebounds+assists), each game section
marked `CAPTURED` / `NOT_OFFERED` / `MISSING` with an evidence locator.
DraftKings posts CBB player props only on select, high-profile games,
so a sparse archive is the expected shape — `NOT_OFFERED` is a datum,
not a failure.

Arming terms:

1. **Cadence** is the standing lane law — T-1H and FINAL writes,
   parser-safe grammar, #2792 five-stage receipts on every write. The
   FINAL capture is the only closing record a future grading may use.
2. **First slate: Nov 2, 2026** (the pinned substrate carries 0 games
   on Nov 1 and exactly 50 on Nov 2; this spec assumes no Nov 1 slate,
   and any Nov 1 games capture later confirms are records only).
3. **Every row is record-only**: `counted=false`, no exceptions, until
   a future preregistration is frozen by the owner. Capture volume
   never converts itself into a clock.
4. **Illinois colleges:** capture records the board as posted (a record
   is not a price), but any future pricing, grading, or design use of
   rows from fixtures touching an Illinois college is refused
   fail-closed, under the same ID-based exclusion as every CBB family.

## 2. Prerequisites before any construction may be designed

All three are outstanding; all three are named so the archive's
existence never gets mistaken for readiness.

1. **Player-box schema verification.** Grading a prop needs the
   player's actual game line. Draft PR #2835 admitted the hoopR
   player-box asset on **bytes + hash only — its schema is
   documented-only**. A schema-verified successor manifest is required
   before outcomes can be joined to captured props at scale.
2. **Player identity crosswalk.** The admitted-crosswalk problem is
   worse here than for teams: the provider crosswalk in PR #2835
   covers teams/schedules, not player identity across DraftKings ↔
   ESPN. Name-only joins are refused. Until a player-identity binding
   is admitted, captured rows are keyed by DK's own identifiers and
   graded by nobody.
3. **Third cross-check — College Basketball Reference (owner-supplied,
   Oct 27, 2026).** sports-reference.com/cbb player pages and game logs
   serve as the independent corroboration that a captured prop's
   (player, game, result) triple is real and correctly keyed, once
   grading is designed — and its schedules cross-check the hoopR
   substrate's slate (which games existed on a date) for capture
   completeness audits. Role: cross-check / reference only. It
   publishes no odds, so it can never be this family's market baseline;
   it is not an identity admission; the crosswalk stays OPEN until its
   own admission lands.

## 3. The honest horizon

With capture armed from Nov 2, the archive accrues only where DK
chooses to post props. A first construction *design* becomes
debatable only after §2.1–§2.2 land and a non-trivial archive exists —
realistically a later-in-the-season question, stated plainly so no
one schedules a CBB props verdict this spec cannot support. The
family's verified path, when it exists, is the same as every family's:
a frozen preregistration, forward captures, and a passed validation
against the market baseline those captures create.

## 4. Activation state and blockers

State reached: **CAPTURE-ARMED (spec)** — capture may begin under
PR #2820 the moment CBB capture itself is live. Blockers, one line
each:

- Player-box schema is unverified (PR #2835 admitted bytes+hash only).
- No admitted player-identity binding exists (DK ↔ ESPN).
- Historical prop lines are NO_DATA (G1/G5) — no screen is possible,
  now or later; forward capture is the only path.
