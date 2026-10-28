# DESIGN + PREREGISTRATION DRAFT — CBB Sides / Totals

# DRAFT — NOT FROZEN — NOT IN FORCE — NO GAMES COUNT

**Design status: CONSTRUCTION DESIGNED + DESIGN-SCREEN SPECIFIED (UNRUN)
+ FORWARD PREREG DRAFTED. The historical screen specified in §3 produces
DESIGN evidence only — it can never validate this family. Freezing is
the owner's act, and §5's data gates must hold before any row can
count.** Date: 2026-10-28. Families: CBB spread, moneyline, game total —
recorded NO_CONSTRUCTION (gap plan, Oct 27, 2026), capture-first.

Composition note: open PRs #2152 (CBB as-of ratings model / ESPN-ID
binder), #2197 (fixture IDs), #2350 (game/halves + player foundations,
Illinois exclusion) and #2280 (DK captured-market evidence contract)
already claim implementation areas (see
`research/cbb_season_prep_20261020/READINESS_CONTRACT_DRAFT.md`). This
document is the activation design and test draft for the family; it
reimplements none of that work, and where an implementation lands under
those PRs, this design's screen and prereg terms are what it must be
reconciled against — by the owner, not by assumption.

## 1. Candidate construction — CBB_TORVIK_EFFICIENCY_V1 (draft name)

Inputs are exactly one source: the **morning-of BartTorvik T-Rank
archive row for the game's date D** (`adj_o`, `adj_d`, `adj_tempo`,
`barthag`), taken only via the admitted route of draft PR #2832
(toRvik-data mirror, pinned commit) under its binding as-of rule — the
archive file for D is the rating as of the morning of D; no same-day
post-game data, no later-vintage reconstruction, no silent carry-forward
(a missing file for D makes the fixture NO_DATA).

Mechanics (all parameters fitted strictly walk-forward, §3):

- Expected possessions = blend of the two teams' `adj_tempo`.
- Expected team points = (team `adj_o` + opponent `adj_d` − league mean
  efficiency) / 100 × expected possessions, each term as of D.
- Margin = expected-points difference + home-court term (neutral-site
  fixtures take the term as zero, from a venue flag in the schedule
  substrate — never inferred from team order).
- Game total = sum of expected team points. Moneyline probability from
  the margin via a spread→probability map fitted on strictly prior
  seasons only.

**The existing-model baseline (named now, so the screen is honest):**
the *simple ratings baseline* — raw efficiency differential with a
fixed league-average home-court constant and **no** tempo interaction
for totals. The candidate must beat this baseline, not a strawman: its
claimed additions are exactly (a) per-season home-court estimation and
(b) the tempo blend on totals. If those additions do not pay, the
screen says so.

## 2. Identity, exclusion, and the crosswalk — OPEN, with a third check

Joining Torvik rows (name-based) to hoopR substrate games (ESPN IDs)
requires the ESPN ↔ Torvik ↔ NCAA crosswalk, which is **OPEN — not
admitted** (draft PR #2835: provider crosswalk exists but matches are
confidence-scored, no NCAA game-ID column was observed, 2027 coverage
unverified; name-only joins are refused). Consequences, by layer:

- **Design screen (§3):** an audited name-join is permitted *for design
  evidence only*, with the ambiguity list published in the screen
  output and every ambiguous fixture excluded. Illinois fixtures are
  **conservatively over-excluded** on name/conference match — a
  design-screen expedient that can only remove games, never admit one.
- **Forward prereg (§5):** no such expedient exists. The production
  Illinois-college exclusion is ID-based and fail-closed (PR #2832
  §6); the prereg cannot count until the crosswalk admission and the
  exclusion registry are in force.

**Third cross-check — College Basketball Reference (owner-supplied,
Oct 27, 2026).** Sports Reference's College Basketball Reference
section (sports-reference.com/cbb) carries full D1 schedules/results
and school history, free to browse. In this design it is a third,
independent cross-check on the two admitted substrates: a fixture
enters the §3 screen only on **three-way agreement** — hoopR substrate
(ESPN game ID, date, teams, final score), Torvik archive (a morning-of
file exists for that date and carries both teams), and College
Basketball Reference's season schedule (same fixture, same date, same
final score). Any disagreement excludes the fixture and is logged as
`SCHEDULE_DISCREPANCY`, never silently resolved. CBB Reference school
pages (location / conference) additionally corroborate the conservative
Illinois over-exclusion above. **Role limits: cross-check / reference
only.** It is not a ratings input (no CBB-Reference metric enters the
construction), not a validation or market baseline (it publishes no
odds), and not an identity admission (the crosswalk stays OPEN until
its own admission verifies exact-match coverage). Evidence state:
documented-only (owner-supplied source list); no bytes were pulled
from it for this design.

## 3. Design screen spec (historical — DESIGN EVIDENCE ONLY)

- **Seasons:** the admitted archive's coverage, 2014-15 → 2022-23.
  These seasons are design data; several were visible to earlier CBB
  exploration, and nothing about this screen is out-of-sample in the
  validating sense.
- **Data pins before any run:** (a) Torvik archive files via the #2832
  retrieval script at its pinned commit, one file per game date;
  (b) historical schedule/results assets from the sportsdataverse-data
  releases pinned by the full-tuple rule of draft PR #2835 (tag +
  release ID + asset ID + size + updated_at + SHA-256) under a
  successor manifest — #2835 pinned the 2027 schedule and 2026 player
  box only, so this pin is outstanding work, named here; (c) the §2
  three-way fixture agreement, applied before any fitting.
- **Protocol:** walk-forward by season — parameters (home-court term,
  spread→probability map) fitted on seasons strictly before the scored
  season; ratings always the morning-of file for each game date.
- **Metrics and bar:** spread MAE and total MAE, candidate vs (i) a
  naive league-mean baseline and (ii) the §1 simple ratings baseline;
  paired, season-block bootstrap CIs. **Design pass** = CI upper bound
  < 0 against *both* baselines on *both* legs. A design pass earns only
  freeze *eligibility* for §5 — it is labelled DESIGN_PASS, never
  validation, and it does not change the family's recorded state.
- KenPom data enters nowhere, in any leg, directly or via mirror.

## 4. What the screen cannot fix

The admitted Torvik route's coverage **ends in the 2022-23 season**;
the current CRAN route (api.cbbstat.com) failed its probe from the
SportsEdge runtime and is NOT ADMITTED (PR #2832). There is therefore
**no lawful morning-of ratings source for 2026-27 games today**. A
live-season route needs its own successful probe + hash pin (a sibling
workstream is hunting one). Until then §5 cannot count a single row —
this is the family's binding blocker, and no design language in this
document softens it.

## 5. Forward preregistration draft (terms to freeze verbatim)

- **Population:** 2026-27 NCAA Division I regular-season games on or
  after the freeze date, excluding any fixture touching an Illinois
  college (ID-based, fail-closed) and any fixture failing identity
  verification. **First possible slate: Nov 2, 2026** — the pinned
  schedule substrate carries 0 games on Nov 1 and exactly 50 on Nov 2,
  and this prereg assumes no Nov 1 slate. (A lane document, draft PR
  #2820, reports an ESPN-feed discrepancy suggesting a possible Nov 1
  Rome game; that claim is unresolved. If capture confirms Nov 1 games,
  they are capture records only — a freeze must name its first slate,
  and nothing counts retroactively.)
- **Rows:** priced pre-tip from the T-1H DraftKings capture, graded
  against the FINAL capture's closing line, under the #2820 capture
  scope (seven default sections) and #2792 five-stage receipts.
- **Data gates (all must hold before counting):** (i) live-season
  Torvik morning-of route admitted with hash pins (§4); (ii) identity
  crosswalk admitted and the Illinois exclusion registry in force
  (§2); (iii) capture delivery proven on the opening slates.
- **Legs:** accuracy — paired spread/total MAE vs the §1 simple
  ratings baseline recomputed forward, CI upper < 0; market — CLV > 0
  and ROI > 0 vs the closing line at captured prices.
- **Verdict:** once, at the first slate close with ≥ 40 distinct
  graded games (standing minimum-gate clarification), both legs read
  together; no re-review absent a new preregistration.

## 6. Activation state and blockers

State reached: **DESIGN + DESIGN-SCREEN SPEC + PREREG DRAFTED.**
Blockers, one line each:

- Live-season (2026-27) Torvik morning-of route is not admitted — the
  binding blocker for any forward counting.
- ESPN ↔ Torvik ↔ NCAA identity crosswalk is OPEN, not admitted —
  production Illinois exclusion depends on it.
- Historical schedule/results full-tuple pin (successor manifest to
  PR #2835) is outstanding — the design screen cannot run until it lands.
