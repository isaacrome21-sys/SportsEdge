# AMENDMENT 3 (DRAFT) — CBB FIRST-HALF LINES (1H spread / 1H total): completion of the §2 design-screen spec (verdict rule, climatology baseline, share estimator, scored seasons, inference, fixture universe)

**Status: DRAFT — NOT ADOPTED. This draft adopts nothing,
changes no term by landing, freezes nothing, and counts
nothing.** It is drafted in the manner of Amendment 1
(`AMENDMENT_1.md` in this directory, PR #2883) and Amendment 2
(`AMENDMENT_2_DRAFT.md` in this directory, PR #2906): it
becomes part of the design it completes only by the owner's
recorded adoption act, with its own independent review closed
on the exact head carrying the adoption. Until adoption, the
CBB first-half family remains **DESIGN ONLY — NO
CONSTRUCTION RUN — NO CLOCK**, `verified_play = false`,
PAPER / 0u, and its design screen remains **NOT_EXECUTABLE**
on the record of attempt 1 (PR #2911). Adoption of this
amendment would not itself run the screen: the screen runs
afterwards as a new attempt, on its own record, exactly as
attempt 4 of the sibling efficiency screen ran under
Amendment 1.

**What this amendment is.** The 1H design screen attempt 1
(`research/cbb_first_half_screen_20261028/screen_result.json`,
PR #2911) returned **NOT_EXECUTABLE —
`SCREEN_SPEC_INCOMPLETE_1H`**. The design's named data
prerequisite is satisfied (hoopR play-by-play pinned full-tuple
with schema verification, PR #2901; Method A halftime
derivation admitted; the final-agreement consumer gate
binding), but §2 of the 1H design
(`CBB_TEAM_TOTALS_1H_DESIGN.md`) is a screen **shape**: it
names the metrics (1H-total MAE and 1H-margin MAE) and one
baseline by name, and six places where the text does not
reach, so that two honest executors would compute different
verdicts from the same fixtures:

- **G-1H-1 — No verdict rule.** No CI test, threshold, or
  DESIGN_PASS condition is stated for either 1H leg. The
  parent §3 bar is written for the spread/total legs and §2
  does not import it — unlike §1 of the same design, which
  imports §3's protocol and CI for the team-totals leg
  explicitly.
- **G-1H-2 — Baseline named, never constructed.** "Naive
  half-share climatology" is named, but what full-game
  expectation it scales and how its share is estimated are
  both unstated.
- **G-1H-3 — Share estimator undefined.** The candidate's "one
  share for team points" has no estimator: ratio form,
  league-wide vs per-team, overtime treatment, and fitting
  universe are unstated.
- **G-1H-4 — No scored-season set.** §2 names no season span;
  the pinned PBP begins 2014-15, and under the strictly-prior
  fitting rule the first season's status (scored vs fit-only)
  is undecided in the text.
- **G-1H-5 — No inference procedure.** No bootstrap design,
  resample count, or seed is declared for the 1H legs.
- **G-1H-6 — Fixture-universe composition unstated.** Whether
  the scored universe is the parent screens' three-way-agreed
  universe intersected with the PBP final-agreement gate, or
  the schedule universe under the PBP gate alone, is a choice
  the text never makes.

This amendment supplies exactly those six missing pieces of
machinery, and nothing else. **It does not alter any existing
term of the 1H design or of the parent design** — not the
construction (§1 of the parent design, whose full-game
expectations the 1H forecast scales), not the "one share for
team points, applied to margin and total alike" form, not the
strictly-prior fitting rule, not the named metrics, not the
data prerequisite, not the Illinois exclusion, and not §2's
forward terms, whose completion is **not** this amendment's
scope (§7). Each added term is indexed in §8 to its
provenance: **adopted-from** (a program form carried
unchanged), **adapted-from** (a program form adjusted to this
family, with the adjustment and its reason stated), or
**NEW** (no program form exists; the narrowest term that
makes the leg computable). One term — the G-1H-2 baseline
construction — admits two readings the texts do not settle;
both are constructed in full in §2 and the choice is carried
as **ADOPTION-REVIEW FLAG 1** for the adoption act to settle
expressly, in the manner of the reading Amendment 2's review
carried for its families.

**Drafting basis.** The parent design
(`CBB_SIDES_TOTALS_DESIGN_AND_PREREG_DRAFT.md`) §§1–3; §1 of
the 1H design itself, whose express import of the §3 protocol
is the pattern §2 omits; the sibling screens **as executed**
(attempt 4, PR #2891, `screen_result_attempt4.json`; team
totals, PR #2892, `screen_result.json`) — the forms those
screens actually ran, not merely the forms their designs
sketched; Amendment 1's prior-snapshot convention (PR #2883),
which governs every Torvik input the candidate consumes; and
the PBP admission record (PR #2901), whose Method-A
final-agreement gate binds every consumption of a halftime
score, this screen's included.

---

## 1. G-1H-1 — Verdict rule for both 1H legs

The screen's verdict rule is the parent §3 bar, imported for
the 1H legs in the same manner as §1 of the 1H design imports
it for the team-totals leg:

- **Legs and statistic.** Two legs: 1H-total MAE and 1H-margin
  MAE. For each leg, the statistic is the mean **paired
  difference** per fixture — candidate absolute error minus
  baseline absolute error, paired on the same fixture against
  the same Method-A derived 1H outcome — candidate and
  baseline as constructed in §2 and §3 below.
- **Design pass.** **DESIGN_PASS = the §5 interval's upper
  bound < 0 on both legs** (the climatology baseline of §2 is
  the baseline of both legs). A failure of either leg is
  recorded **FAILED_SCREEN** (the design's DESIGN_FAIL), with
  both legs' statistics published either way. A design pass
  earns only what the parent §3 says a design pass earns:
  freeze *eligibility* for a forward preregistration, labelled
  DESIGN evidence — never validation, and it does not change
  the family's recorded state by itself.
- **One baseline, deliberately.** §2 of the design names
  exactly one baseline for 1H. No second leg against the §1
  simple ratings baseline is supplied: adding one would be a
  new leg, not a completion. The comparison the design poses
  is whether the parent's full-game expectations, scaled by a
  PBP-fitted share, beat first-half climatology; the parent
  construction's own contest against the simple baseline was
  the parent screen's question and stands on that record.

*Provenance: adapted-from parent §3 (the bar "CI upper bound
< 0", the FAILED_SCREEN recording) via the import pattern of
1H design §1 — the import §1 makes expressly for team totals
and §2 omits; the two-leg/one-baseline shape is the design's
own text, completed, not extended.*

## 2. G-1H-2 — The naive half-share climatology baseline

**ADOPTION-REVIEW FLAG 1 — two readings; the adoption act
must confirm one by name.** The design's phrase "naive
half-share climatology baseline" supports two constructions,
both fully specified here. They are not equivalent, and they
do not test the same thing; §2 of the design does not settle
between them, and this draft does not silently pick one.

- **Reading A — climatology of the 1H quantities themselves.**
  The baseline forecast for a scored fixture is the
  **strictly-prior league mean of the actual 1H quantity**:
  prior seasons' mean actual 1H total for the total leg,
  prior seasons' mean actual 1H margin for the margin leg,
  fitted walk-forward per scored season on the §6 fitting
  universe (Method-A gated fixtures of the composed universe,
  seasons strictly before the scored season). This is the
  executed sibling screens' naive league-mean construction
  (attempt 4's runner: "prior seasons' mean actual margin /
  mean actual total") restated on the 1H quantities — under
  this reading "half-share" describes the quantities (first
  halves), and no share is estimated at all. The leg then
  tests the whole candidate — full-game expectations ×
  fitted share — against raw first-half league averages.
- **Reading B — naive full-game expectation × climatological
  share.** The baseline forecast is the sibling screens'
  **naive league-mean full-game expectation** (prior seasons'
  mean actual full-game total / full-game margin, fitted
  identically) **scaled by a climatological first-half
  share** estimated by the §3 estimator on the same
  strictly-prior fitting universe. This is the name-literal
  reading: a *half-share* climatology. **Disclosed
  consequence:** under the §3 estimator, the climatological
  share and the candidate's fitted share are the same number
  in any scored season (same estimator, same fitting
  universe, same window) — so under Reading B the two legs
  test the full-game expectations alone, rescaled to the
  first half, and the fitted share itself is never what is
  being graded. That may be exactly what a naive baseline is
  for; it is stated here so the adoption chooses it knowingly
  rather than discovering it in the run.

Under either reading: the baseline is fitted on seasons
strictly before the scored season, on the §6 fitting
universe, with no other input; KenPom data enters nowhere, as
in the parent design.

*Provenance: Reading A adapted-from the executed naive
league-mean construction of PR #2891's screen (reading 1 of
its runner record); Reading B NEW as a construction, built
only from forms the record already contains (the same naive
means × the §3 share); the choice between them is
ADOPTION-REVIEW FLAG 1.*

## 3. G-1H-3 — The first-half share estimator

The design fixes the parameter's shape — "one share for team
points, applied to margin and total alike in V1", under §2's
own heading of "one extra parameter" — and this section
supplies only its estimator:

- **Form: ratio of sums over team-games.** For scored season
  S, the share is
  `s(S) = Σ 1H team points ÷ Σ full-game team points`,
  summed over every team-game in the fitting window (both
  teams of every fitting fixture). The candidate forecast is
  then: 1H team points = full-game expected team points ×
  s(S); 1H total = expected game total × s(S); 1H margin =
  expected margin × s(S) — the design's stated application to
  margin and total alike.
- **League-wide, one parameter.** The share is a single
  league-wide number per scored season — the design's "one
  share" and "one extra parameter" admit no per-team shares
  in V1; per-team shares are among the V2 questions the
  design reserves ("separate margin/total shares are a V2
  question the data must earn"), and are not supplied.
- **Overtime.** Full-game team points are the **official
  final points, overtime included** — the same final the
  admission's consumer gate checks the derived final against.
  1H team points are periods 1–2 only (overtime is never a
  first-half period). Overtime games are **included** in the
  fitting universe on those terms. *Disclosure of the
  reading:* excluding overtime games instead would raise the
  fitted share slightly (their denominators carry OT points
  their numerators cannot); inclusion is the narrower choice
  because it uses the gate's own final, undeflected, and
  invents no exclusion the design does not name.
- **Fitting window and universe.** Fitted walk-forward: for
  scored season S, the window is all seasons strictly before
  S, over the fixtures of the §6 composed universe that pass
  the Method-A final-agreement gate. A fixture whose halftime
  cannot be consumed under the gate contributes to neither
  the share's numerator nor its denominator — fitting is
  consumption, and the admission's gate binds it identically.
  No share is borrowed from the NBA fit, from a rule of
  thumb, or from halving final scores (the design's own
  refusals, carried unchanged).
- **Mean-of-ratios considered and not taken.** A per-game
  mean of ratios (each team-game's 1H ÷ full-game, averaged)
  weights a 40-point team-game equally with a 90-point one
  and is not the aggregate share the design's "a first-half
  share" names; the ratio of sums is the aggregate share of
  all points scored that were scored in first halves, and it
  is the form the sibling screens' fitted league means take
  (sums over fixtures ÷ fixture counts). The alternative is
  recorded here so the choice is reviewable, not silent.

*Provenance: the parameter's shape is the design's own §2
text (adopted-from the design); the estimator is NEW — the
narrowest form that computes the named parameter — with the
fitting universe adopted-from the PR #2901 admission's
binding consumer gate and the window adopted-from the
design's strictly-prior rule.*

## 4. G-1H-4 — Scored seasons; the first season is fit-only

- **Scored seasons: 2015-16 through 2022-23** (eight seasons)
  — the span the pinned PBP covers (season files ending
  2015–2023) inside the parent design's §3 season span
  (2014-15 → 2022-23).
- **2014-15 is the initial fitting window and is not
  scored.** Under the design's strictly-prior rule there is
  no season before 2014-15 in any pinned source from which
  the share — or the parent construction's walk-forward
  parameters — could be fitted, so no honest 2014-15 score
  exists. This is the executed sibling screens' own reading
  (attempt 4, reading 1: "2014-15 is the initial fitting
  window and is not scored"; its first scored season,
  2015-16, was fitted on 2,989 fixtures of 2014-15), carried
  unchanged; the team-totals screen ran the same span.

*Provenance: adopted-from the executed sibling screens
(PR #2891 attempt 4; PR #2892) under the parent §3 protocol —
the season span is the parent's, the fit-only first season is
the executors' recorded reading of the strictly-prior rule
this design also states.*

## 5. G-1H-5 — Inference procedure

- **Construction: paired season-block bootstrap**, identical
  in form to the executed sibling screens: resample the
  **scored seasons (blocks) with replacement** — each
  resample draws 8 blocks from the 8 scored seasons and
  recomputes the pooled mean paired difference from the
  per-season (sum, n) aggregates — **10,000 resamples**,
  **seed 20261028** (the only seed either sibling family's
  record has ever bound, carried unchanged), **two-sided
  percentile 95% interval** on the mean paired difference,
  per leg. §1's "CI upper < 0" reads this interval's upper
  bound, per leg.
- **Why not the game-cluster form.** Amendment 2 §2 adopts a
  game-cluster bootstrap for the siblings' **forward** legs,
  and states why in its own text: the §3 season-block form
  "is a screen term over eight historical season blocks; a
  single in-progress forward season has no season blocks, so
  it does not transfer by its own words." The converse holds
  here: this screen **has** season blocks — the same eight
  the sibling screens resampled — so the screen form
  transfers and the forward form is not imported. If a 1H
  forward preregistration is ever drafted after a design
  pass, its interval construction is that document's term to
  state, as Amendment 2 was for its families.

*Provenance: adopted-from parent §3 as executed in PR #2891
attempt 4 and PR #2892 (season-block bootstrap, 10,000
resamples, seed 20261028, percentile 95%); the non-import of
the game-cluster form is adapted-from Amendment 2 §2's own
reasoning, applied in reverse.*

## 6. G-1H-6 — Fixture-universe composition

- **Scored universe** = the parent screens' **three-way-agreed
  universe** — hoopR substrate, Torvik archive (under
  Amendment 1's prior-snapshot leg), and College Basketball
  Reference in agreement, with the parent §2 ambiguity
  exclusions and the conservative Illinois over-exclusion
  applied exactly as executed (26,553 fixtures in PRs
  #2891/#2892) — **intersected with** the PBP admission's
  **Method-A final-agreement gate**: a fixture is scored only
  if its derived halftime may be consumed (derived final =
  admitted schedule final). Fixtures failing the gate are
  excluded and counted, per season, in the run's universe
  table; they are NO_DATA for this screen, never repaired by
  Method B (refused) or by any substitute halftime source.
- **Fitting universe** (share, §3; baselines, §2) = the same
  composed universe restricted to seasons strictly before the
  scored season, under the same gate.
- **The alternative composition, stated and not taken.** The
  schedule universe under the PBP gate alone (47,903 fixtures
  in the admission manifest) was the other candidate. It is
  not taken, for a reason of scope rather than preference:
  on most of those fixtures the candidate's full-game
  expectation **does not exist** under the parent design —
  the Torvik leg and the three-way agreement are the parent
  §2 gate that defines where
  `CBB_TORVIK_EFFICIENCY_V1` emits an expectation at all —
  so scoring there would require amending the parent
  design's fixture gate, which this amendment does not do
  and may not do silently (§7). The intersection is the only
  composition on which both sides of every paired difference
  — candidate expectation and gated 1H outcome — exist under
  terms already in force.

*Provenance: adapted-from parent §2 (the three-way gate, as
amended by Amendment 1) composed with the PR #2901
admission's binding consumer gate; the counts 26,553 /
47,903 are the records' own — the intersection count is the
future run's to compute and publish, and is not asserted
here.*

## 7. What does NOT change; scope

Nothing in this amendment alters, restates with different
effect, or re-opens:

- any term of `CBB_TEAM_TOTALS_1H_DESIGN.md` §1 (team totals
  — a sibling family whose screen has run and whose forward
  completion is Amendment 2's subject, not this one's);
- any term of the parent design — its §1 construction, §2
  fixture gate, §3 screen spec and bar for its own legs, or
  §5 forward draft;
- the PBP admission's scope lock (PR #2901): design-screen
  use for the CBB 1H family only, Method A only, the
  final-agreement gate binding — this amendment consumes the
  admission inside its admitted scope and extends it nowhere;
- the attempt-1 record (PR #2911) or the PR #2892 first-half
  record: both stand as executed at their run times; this
  amendment supersedes attempt 1's stated *reason* only if
  and when it is adopted, and attempt 1's verdict —
  NOT_EXECUTABLE — remains the family's screen state until a
  post-adoption attempt runs;
- **the 1H forward terms.** §2 of the design states forward
  terms in shape only ("then mirror §1's"). This amendment
  completes the **design screen**; it supplies no pick rule,
  no close-validity rule, and no forward interval
  construction for 1H, and no forward clock is drafted,
  armed, or implied by it. As with the sibling families —
  whose §5 completion (Amendment 2) followed their screens —
  a 1H forward completion is a later instrument, drafted
  only if the screen passes.

## 8. Provenance index

| Added term | Where | Provenance |
|---|---|---|
| Verdict rule: CI upper < 0 on both legs; FAILED_SCREEN recording | §1 | adapted-from parent §3 via 1H design §1's import pattern |
| One-baseline shape (no simple-ratings leg added) | §1 | the design's own §2 text, completed not extended |
| Baseline Reading A (prior means of 1H actuals) | §2 | adapted-from the executed naive league-mean construction (PR #2891) |
| Baseline Reading B (naive full-game means × climatological share) | §2 | NEW construction from record forms; **choice = ADOPTION-REVIEW FLAG 1** |
| Share estimator: ratio of sums over team-games; league-wide single share | §3 | shape adopted-from design §2; estimator NEW (narrowest form), alternatives recorded |
| Overtime: official final incl. OT; OT games included in fitting | §3 | NEW reading on the admission gate's own final, disclosed |
| Fitting window (strictly prior) and gated fitting universe | §3 | adopted-from design §2 rule + PR #2901 binding gate |
| Scored seasons 2015-16 → 2022-23; 2014-15 fit-only | §4 | adopted-from executed sibling screens (PRs #2891/#2892) under parent §3 |
| Season-block bootstrap; 10,000 resamples; seed 20261028; percentile 95% | §5 | adopted-from parent §3 as executed (PRs #2891/#2892) |
| Non-import of the game-cluster (forward) form | §5 | adapted-from Amendment 2 §2's reasoning, applied in reverse |
| Universe: three-way-agreed ∩ Method-A gate; fitting universe likewise | §6 | adapted-from parent §2 (as amended by Amendment 1) + PR #2901 gate |
| Alternative universe (schedule under gate alone) not taken | §6 | NEW scope reasoning, stated in full |

## 9. Adoption and effect

Adoption is the owner's recorded act, in the manner of
Amendments 1 and 2: independent review closed on the exact
head carrying the adoption, the owner's authorization
recorded, and the adoption recorded by merge — never by this
draft's landing, a commit, or a review comment. The adoption
act must additionally **confirm ADOPTION-REVIEW FLAG 1 by
name** (Reading A or Reading B of §2); an adoption silent on
the flag leaves G-1H-2 unsupplied and the screen
NOT_EXECUTABLE. On adoption, gaps G-1H-1 through G-1H-6 in
the attempt-1 record stand supplied by this amendment (the
design's text is never edited; amendments supersede by
reference). Adoption alone still runs nothing, freezes
nothing, and counts nothing: the screen then runs as
attempt 2 under the completed spec, on its own record, and
its verdict — DESIGN_PASS or FAILED_SCREEN — is whatever the
run computes. If any term of this amendment is read to
conflict with the 1H design or the parent design as written,
the designs govern and the conflict is itself recorded as a
defect for the adoption's review to resolve — this amendment
completes the §2 screen spec; it does not outrank it.

*Drafted Oct 28, 2026, from the 1H design and parent design
of record, the attempt-1 screen record (PR #2911), the
executed sibling screens (PRs #2891 / #2892), Amendment 1
(PR #2883), Amendment 2 (PR #2906), and the PBP admission
(PR #2901). DRAFT — not adopted, not frozen; nothing counts.*
