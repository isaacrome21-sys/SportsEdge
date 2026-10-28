# PREREGISTRATION — CBB_TORVIK_EFFICIENCY_V1 (CBB spread & game total)

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

**Provenance:** the terms in §1 are §5 of the design of record,
`research/nba_cbb_activation_20261028/CBB_SIDES_TOTALS_DESIGN_AND_PREREG_DRAFT.md`
(sha256 `cacbee09e1ea53c68888e5b7be3c2d61cd99def6eaba9980c0236e89daccb2fd`, merged in PR #2843), transcribed verbatim —
no statistical term, threshold, pass criterion, or rule differs
from the design. Finalization adds only: this status/provenance
block, the construction-of-record statement (§2), the design
evidence with its disclosure (§3), the data-gate status (§4), the
first-counted-slate statement (§5), the multiple-testing and seed
statement (§6), the recorded readings (§7), the blocking gaps
(§8), and the pins (§9). Prepared at main `c04e55052`.

**Design evidence:** the §3 design screen of the design of record,
executed as attempt 4 under Amendment 1's prior-snapshot
convention (PR #2883; the archive file for date D is an
end-of-day snapshot, so the screen read file D−1), returned
**DESIGN_PASS** (PR #2891): pooled candidate spread MAE 8.899 /
total MAE 13.812 vs naive 11.045 / 15.687 vs the §1 simple
ratings baseline 8.904 / 14.710, n = 23,564 scored fixtures,
all four criteria passing. **Disclosure, exactly as the screen
report makes it: criterion 2 — spread MAE vs the simple ratings
baseline — passes by a negligible margin: mean paired difference
−0.005 MAE points, CI [−0.008, −0.001]; the candidate's spread
advantage over the simple baseline is practically nil
(mechanically expected: on the spread leg the candidate's only
addition over the baseline is per-season home-court estimation;
it is worse than the baseline in 2016-17, 8.707 vs 8.701, and
within ±0.011 in every other scored season). No reader should
mistake criterion 2 for evidence of a meaningful spread edge
over the simple baseline; the screen's substantive findings are
criteria 1, 3 and 4.** A design pass is freeze *eligibility*
only — DESIGN evidence, never validation.

**Verified, as this preregistration uses the word** (owner
ruling, Oct 27, 2026, repealing the 50-graded-picks gate): a
market is VERIFIED when this preregistration's chronological
out-of-sample validation **passes in full** against BOTH
baselines — the existing model (here, the design's §1 simple
ratings baseline, recomputed forward) and the contemporaneous
market baseline (captured DraftKings lines). Forward grading
(CLV/ROI reporting) continues after any verdict per standing
law; it is the passage of §1's legs, not a pick count, that
carries the label. PLAY eligibility additionally faces the
program's multiple-testing policy (primary test at α = 0.05/k,
k = the number of validated families on the verdict date).

---

## 1. Terms (design §5, verbatim)

The design's §5 is headed "Forward preregistration draft (terms
to freeze verbatim)". Its five bullets follow unaltered:

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

## 2. Construction of record

`CBB_TORVIK_EFFICIENCY_V1`, as specified in §1 of the design of
record: expected possessions = blend of the two teams'
`adj_tempo`; expected team points = (team `adj_o` + opponent
`adj_d` − league mean efficiency) / 100 × expected possessions;
margin = expected-points difference + home-court term (zero at
neutral sites, from a venue flag in the schedule substrate —
never inferred from team order); game total = sum of expected
team points; parameters fitted strictly walk-forward. The
executable of record at package time is the attempt-4 screen
runner, `run_screen_attempt4.py` in this directory (sha256
`75479ea14b2ab4ef954bd4cde629a2d00e24efea173ac61c695482890dd4c45e`), which implements exactly these mechanics on
the admitted archive route. **Finding F-1 (act prerequisite, not
a term): no built forward runner exists.** No module on main
prices this construction from the live route for forward rows;
the freeze act therefore includes the forward-runner build
(pinned in the freeze record, with a NON_COUNTED landing check
reproducing the screen runner's outputs on a historical date)
before its review closes — see the checklist. The design's
moneyline probability map (§1 of the design) is part of the
construction but carries no forward leg — see reading A-1.

## 3. Input convention for the forward test (reading R-1)

§1's population is the 2026-27 season and its data gate (i)
names the **live-season Torvik morning-of route** — the route
admitted in PR #2841 (`barttorvik.com/{year}_team_results.csv`,
one hash-pinned pull each morning before first tip under the
`torvik-morning-pull-daily` job, whose body now carries
Amendment 1 §7's late-pull guard: a pull after any of the day's
games have started is not a morning-of snapshot for that date).
**Reading R-1: the forward input for a game on date D is D's
morning-of live-route vintage.** Amendment 1's prior-snapshot
(D−1) convention is **not** the forward input rule: by its own
§6 it "governs the design screen only" and "nothing here
pre-adopts the convention for" a forward preregistration; the
archive it governs has no 2026-27 coverage in any case (design
§4). This reading is recorded here for the act's review to
confirm or correct; it changes no §1 term.

## 4. Data gates — status at package time

§1's three data gates, against current main:

- **(i) Live-season Torvik morning-of route admitted with hash
  pins — SATISFIED.** PR #2841 admission; the daily job's first
  pull landed 2026-10-28 (365 teams, hash-pinned manifest); the
  late-pull guard is in the job body.
- **(ii) Identity crosswalk admitted and the Illinois exclusion
  registry in force — SATISFIED.** Crosswalk PR #2898 on main
  (`research/cbb_identity_crosswalk_20261028/`, 369-team
  registry; Illinois colleges flagged
  `capture_excluded_illinois`); the production exclusion is
  ID-based and fail-closed in `sportsedge/cbb_capture_scope.py`
  (ESPN-ID denylist).
- **(iii) Capture delivery proven on the opening slates — OPEN.**
  The `cbb-capture-landing-precheck-20261101` job fires Sun
  Nov 1, 07:00 CT; gate (iii) closes only on its evidence plus
  the opening slates' delivery receipts (Nov 1 Rome game —
  Notre Dame @ Villanova, ESPN 401920982, 08:30 CT — and the
  Nov 2 slate). **No freeze act before this gate closes.**

## 5. First counted slate

In the prospective form of the NFL team-totals freeze record:
**the first counted slate is the first slate priced by the
pinned forward runner after the freeze-act merge; no backfill —
rows priced before the merge never count.** §1's own floor
applies unchanged: the first possible slate is Nov 2, 2026 (the
pinned schedule substrate carries 0 games on Nov 1 and exactly
50 on Nov 2); if capture confirms Nov 1 games (the Rome game),
they are capture records only, exactly as §1 states.

## 6. Multiple testing and seed (package-stated program discipline)

§1 states no seed and no interval level; the following is
program discipline stated by this package for the act to bind —
it is not a §1 term and does not complete gap G-2. Per the
Oct 22, 2026 multiple-testing policy, verdict intervals are
judged at α = 0.05/k with k computed in
`FREEZE_ACT_CHECKLIST.md` (**k = 12** at package time). **Seed:
20261028 binds** — the only seed this family's record has ever
bound (the design screen's preregistered bootstrap seed,
attempt 4 report §3; carried unchanged). The freeze record
instantiates both at the act; recomputation of k at the act and
at the verdict may only raise it.

## 7. Recorded readings

- **A-1 — Moneyline scope.** The design's family header names
  "CBB spread, moneyline, game total", but §3's screen and §1's
  forward legs grade spread and total only; no moneyline leg
  exists in the terms. Reading: moneyline rows are not part of
  this forward test — the draft config registers SPREAD and
  TOTAL only, and no moneyline claim may be made under this
  preregistration. If the owner wants moneyline tested, that is
  a design amendment, not a reading this package may widen.
- **A-2 — Verdict unit.** §1's verdict gate is "≥ 40 distinct
  graded games" — games, not rows or slates; the draft config's
  `min_events` carries it. §1 states no row or slate minimum;
  none is registered.
- **R-1** — the forward input convention, §3 above.

## Blocking gaps — the design's forward terms are incomplete here

The transcription above is complete and unaltered; what follows
is not a term this package adds but the record of where §5
does not reach. **Each gap blocks the freeze act**: the act
cannot execute until a design amendment — the owner's act, with
its own independent review, in the manner of Amendment 1 —
supplies the missing term. Nothing in this package invents,
borrows, or defaults a value for any of them; in particular the
NFL team-totals preregistration's pick rule, close rules, and
interval construction were **not** imported, because they are
that family's frozen terms, not this one's.

- **G-1 — No pick rule for the market leg.** §5's market leg
  requires "CLV > 0 and ROI > 0 vs the closing line at captured
  prices", but no term anywhere in the design states which rows
  are selections, which side of a row is taken, or the stake
  convention. ROI is undefined without them, and CLV needs a
  designated side per row. Two honest executors would compute
  different market legs from the same rows. The operative card's
  EV gates are card-presentation rules, not preregistration
  terms, and were not imported.
- **G-2 — No interval construction for the accuracy leg.**
  §5 requires "CI upper < 0" but states no method, no
  resample count, and no confidence level for the forward test.
  (The §3 design screen's construction — paired season-block
  bootstrap, 10,000 resamples, 95% — is a screen term over eight
  historical season blocks; a single in-progress forward season
  has no season blocks, so it does not transfer by its own
  words.) The seed stated in this package (§6) binds
  whatever construction the amendment declares; it does not
  substitute for one.
- **G-3 — No close-validity or missing-close rule.** §5
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
main: this document, the checklist, the draft config, the design
of record, Amendment 1, the construction-of-record runner, the
attempt-4 screen report and result, the identity crosswalk, the
capture-scope module, and the family tests. The freeze act
recomputes every pin on its own head; a moved pin stops the act.
