# PREREGISTRATION — CBB TEAM TOTALS (readout of CBB_TORVIK_EFFICIENCY_V1)

**Status: FINAL DRAFT — FREEZE PACKAGE, NOT FROZEN. This document
starts no clock, counts no rows, and authorizes no picks.** It is
the finalized preregistration text prepared for the freeze act; it
becomes a preregistration in force only when the freeze act
executes as `FREEZE_ACT_CHECKLIST.md` (this directory) specifies:
(a) independent review has closed on the exact head carrying the
freeze act, (b) the owner authorization is recorded, (c) the
family config flips DRAFT → FROZEN as part of that act, and
(d) the act's merge to main records the freeze — never a commit,
push, or review in this package. Until that merge, the family's
label is **DESIGN ONLY**, `verified_play = false`, PAPER / 0u.

**Provenance:** this family has no standalone design document;
its terms are of record in two places, both transcribed verbatim
in §1 with no statistical term, threshold, pass criterion, or
rule altered: (i) §1 of
`research/nba_cbb_activation_20261028/CBB_TEAM_TOTALS_1H_DESIGN.md`
(sha256 `d206e74a203d50778cc461b4476b2f9f31d4826c3e989ec44b9bb212c486aaac`, merged in PR #2843), which defines the
family as a readout of the parent construction and states its
forward terms by inheritance; and (ii) §5 of the parent design,
`research/nba_cbb_activation_20261028/CBB_SIDES_TOTALS_DESIGN_AND_PREREG_DRAFT.md`
(sha256 `cacbee09e1ea53c68888e5b7be3c2d61cd99def6eaba9980c0236e89daccb2fd`), whose terms the readout inherits.
Finalization adds only: this status/provenance block, the
construction-of-record statement (§2), the design evidence (§3),
the data-gate status (§4), the first-counted-slate statement
(§5), the multiple-testing and seed statement (§6), the recorded
readings (§7), the blocking gaps (§8), and the pins (§9).
Prepared at main `c04e55052`. **CBB first-half lines are a
separate family and are NOT part of this package** — their PBP
prerequisite was admitted in PR #2901 but their screen has not
run and no forward terms for them are prepared here.

**Design evidence:** the team-totals leg of the parent design's
§3 screen, executed under Amendment 1's prior-snapshot
convention (PR #2883), returned **DESIGN_PASS** (PR #2892):
pooled team-points MAE candidate **8.341** vs naive team-mean
9.681 vs the simple ratings baseline's team points 8.723,
n = 23,564 scored fixtures (47,128 team-games); both criteria
pass (paired season-block bootstrap CI upper bounds −1.101 vs
naive and −0.324 vs simple), and the candidate beats both
baselines in all 8 scored seasons. The packet preserves the
original run's record verbatim: the leg's first run (PR #2882)
returned NOT_EXECUTABLE — `AS_OF_PREMISE_FAILURE` under the
design's original morning-of premise, cured for the screen by
Amendment 1's declared convention, not by silence. A design
pass is freeze *eligibility* only — DESIGN evidence, never
validation. Per the design's own rule, this family's verdict is
its own: **a family verdict is never inherited from a sibling
leg** — the parent construction's spread/total DESIGN_PASS
(PR #2891) confers nothing here, and this family's confers
nothing there.

**Verified, as this preregistration uses the word** (owner
ruling, Oct 27, 2026, repealing the 50-graded-picks gate): a
market is VERIFIED when this preregistration's chronological
out-of-sample validation **passes in full** against BOTH
baselines — the existing model (here, the simple ratings
baseline's team points, recomputed forward) and the
contemporaneous market baseline (captured DraftKings lines).
Forward grading (CLV/ROI reporting) continues after any verdict
per standing law; it is the passage of §1's legs, not a pick
count, that carries the label. PLAY eligibility additionally
faces the program's multiple-testing policy (primary test at
α = 0.05/k, k = the number of validated families on the verdict
date).

---

## 1. Terms (verbatim — the readout's own bullet, then the inherited §5)

The team-totals design (§1 of `CBB_TEAM_TOTALS_1H_DESIGN.md`)
defines the family and states its forward terms in one bullet:

> - **Inherits every data gate** of the sides/totals prereg draft
  (live-season Torvik route, admitted crosswalk + Illinois registry,
  capture proof), and its forward terms are the same shape: T-1H
  priced, FINAL-graded, CLV > 0 and ROI > 0 market leg, accuracy leg
  vs the forward-recomputed simple baseline, one verdict at ≥ 40
  distinct graded games.

The inherited terms are §5 of the parent design, headed
"Forward preregistration draft (terms to freeze verbatim)".
Its five bullets follow unaltered:

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

Applied to this family exactly as the design applies them: the
population, rows, and data gates are the parent's; the accuracy
leg is team-points MAE vs the forward-recomputed simple ratings
baseline's team points; the market leg is CLV > 0 and ROI > 0
vs the closing line at captured prices; the verdict is one
verdict at ≥ 40 distinct graded games. The parent §5's accuracy
leg names spread/total MAE for the parent's own markets; this
family's leg is the team-points form the readout design states
— the substitution is the design's own sentence, quoted above,
not this package's editing.

## 2. Construction of record

The expected team points of `CBB_TORVIK_EFFICIENCY_V1` (parent
design §1) *are* the team-total forecasts, home and away — no
second model. The executable of record at package time is
`cbb_team_totals.py` in this directory (sha256
`ac01327a4ed3bb9a37f03e7a9391d2a0918d4f022c86de42bb841a9f15044989`) with its screen runner
`run_team_totals_screen.py`. The construction's recorded
operationalizations stand as flagged in the screen record
(tempo blend = arithmetic mean; naive baseline = prior-seasons
team mean with league fallback) — neither is revisited here.
**Finding F-1 (act prerequisite, not a term): no built forward
runner exists.** No module on main prices this readout from the
live route for forward rows; the freeze act therefore includes
the forward-runner build (pinned in the freeze record, with a
NON_COUNTED landing check reproducing the screen construction's
outputs on a historical date) before its review closes — see
the checklist. The same build may serve the parent family's act
(the construction is shared); each family's pin and verdict
remain its own.

## 3. Input convention for the forward test (reading R-1)

Identical to the parent package's reading, recorded here
independently because this family's act is its own: the forward
input for a game on date D is **D's morning-of live-route
vintage** (PR #2841 route; one hash-pinned pull each morning
before first tip under the `torvik-morning-pull-daily` job,
whose body now carries Amendment 1 §7's late-pull guard).
Amendment 1's prior-snapshot (D−1) convention governs the
design screen only, by its own §6 ("Any forward
preregistration for this construction needs its own terms and
its own review" — the sentence this family's own screen report
also carries), and the archive it governs has no 2026-27
coverage (parent design §4). This reading is recorded for the
act's review to confirm or correct; it changes no §1 term.

## 4. Data gates — status at package time

The readout "inherits every data gate of the sides/totals
prereg draft" (its §1). Against current main:

- **(i) Live-season Torvik morning-of route admitted with hash
  pins — SATISFIED.** PR #2841 admission; the daily job's first
  pull landed 2026-10-28 (365 teams, hash-pinned manifest); the
  late-pull guard is in the job body.
- **(ii) Identity crosswalk admitted and the Illinois exclusion
  registry in force — SATISFIED.** Crosswalk PR #2898 on main
  (369-team registry; Illinois colleges flagged
  `capture_excluded_illinois`); the production exclusion is
  ID-based and fail-closed in `sportsedge/cbb_capture_scope.py`.
- **(iii) Capture delivery proven on the opening slates — OPEN.**
  The `cbb-capture-landing-precheck-20261101` job fires Sun
  Nov 1, 07:00 CT; gate (iii) closes only on its evidence plus
  the opening slates' delivery receipts (Nov 1 Rome game —
  Notre Dame @ Villanova, ESPN 401920982, 08:30 CT — and the
  Nov 2 slate; team-total sections TEAM_TOTAL_AWAY /
  TEAM_TOTAL_HOME are in the capture scope). **No freeze act
  before this gate closes.**

## 5. First counted slate

In the prospective form of the NFL team-totals freeze record:
**the first counted slate is the first slate priced by the
pinned forward runner after the freeze-act merge; no backfill —
rows priced before the merge never count.** The inherited §5
floor applies unchanged: the first possible slate is Nov 2,
2026 (the pinned schedule substrate carries 0 games on Nov 1
and exactly 50 on Nov 2); if capture confirms Nov 1 games (the
Rome game), they are capture records only, exactly as §5
states.

## 6. Multiple testing and seed (package-stated program discipline)

§1 states no seed and no interval level; the following is
program discipline stated by this package for the act to bind —
it is not a §1 term and does not complete gap G-2. Per the
Oct 22, 2026 multiple-testing policy, verdict intervals are
judged at α = 0.05/k with k computed in
`FREEZE_ACT_CHECKLIST.md` (**k = 12** at package time). **Seed:
20261028 binds** — the only seed this family's record has ever
bound (the design screen's bootstrap seed, screen report §§1/4;
carried unchanged). The freeze record instantiates both at the
act; recomputation of k at the act and at the verdict may only
raise it.

## 7. Recorded readings

- **A-1 — Forward accuracy leg names one baseline.** The
  readout design's forward sentence names only "the
  forward-recomputed simple baseline" for the accuracy leg;
  the naive team-mean baseline appears in the screen leg (where
  the candidate beat both) but is **not** named for the forward
  test. Transcribed as written: the forward accuracy leg is vs
  the simple baseline only. No naive leg is added by this
  package.
- **A-2 — Verdict unit.** The inherited gate is "≥ 40 distinct
  graded games" — games, not team-games or rows (this family's
  rows are team-games, two per game); the draft config's
  `min_events` carries it. No row or slate minimum is stated;
  none is registered.
- **R-1** — the forward input convention, §3 above.

## Blocking gaps — the design's forward terms are incomplete here

The transcription above is complete and unaltered; what follows
is not a term this package adds but the record of where §5 (inherited)
does not reach. **Each gap blocks the freeze act**: the act
cannot execute until a design amendment — the owner's act, with
its own independent review, in the manner of Amendment 1 —
supplies the missing term. Nothing in this package invents,
borrows, or defaults a value for any of them; in particular the
NFL team-totals preregistration's pick rule, close rules, and
interval construction were **not** imported, because they are
that family's frozen terms, not this one's.

- **G-1 — No pick rule for the market leg.** §5 (inherited)'s market leg
  requires "CLV > 0 and ROI > 0 vs the closing line at captured
  prices", but no term anywhere in the design states which rows
  are selections, which side of a row is taken, or the stake
  convention. ROI is undefined without them, and CLV needs a
  designated side per row. Two honest executors would compute
  different market legs from the same rows. The operative card's
  EV gates are card-presentation rules, not preregistration
  terms, and were not imported.
- **G-2 — No interval construction for the accuracy leg.**
  §5 (inherited) requires "CI upper < 0" but states no method, no
  resample count, and no confidence level for the forward test.
  (The §3 design screen's construction — paired season-block
  bootstrap, 10,000 resamples, 95% — is a screen term over eight
  historical season blocks; a single in-progress forward season
  has no season blocks, so it does not transfer by its own
  words.) The seed stated in this package (§6) binds
  whatever construction the amendment declares; it does not
  substitute for one.
- **G-3 — No close-validity or missing-close rule.** §5 (inherited)
  grades rows "against the FINAL capture's closing line" but
  states no rule for a row whose game has no FINAL capture, a
  one-sided close, or a stale close: whether such rows are
  excluded, counted toward any insufficiency limit, or void the
  slate is unstated. (The framework defaults carried in
  CONFIG_DRAFT.json — `max_clv_missing_share` 0.2,
  `close_max_age_minutes` 60 — are framework values with no
  preregistration force for this family until the amendment
  fixes the family's own rule; they are carried expressly so
  nothing is inherited silently.)


## 9. Pins

`SPEC_HASHES.txt` in this directory pins, recomputed on current
main: this document, the checklist, the draft config, the
team-totals design of record, the parent design, Amendment 1,
the construction and its screen runner, the screen report and
result, the identity crosswalk, the capture-scope module, and
the family tests. The freeze act recomputes every pin on its
own head; a moved pin stops the act.
