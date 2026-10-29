# FREEZE ACT CHECKLIST — NHL_ATTEMPT2_V1

**Status: CHECKLIST FOR A FUTURE ACT — this document authorizes
nothing, freezes nothing, and starts no clock.** It mirrors the CBB
freeze packages (PRs #2903/#2904) and the NFL team-totals freeze
sequence: the freeze is a separate prospective act, executed by its
own PR, and is recorded **only at that PR's merge**. The sequencing
the NBA props V2 quarantine taught binds throughout: **independent
review closes on the act's exact head BEFORE the merge records the
freeze — review first, freeze second, no exceptions.** Nothing in
this freeze package is in force at any point. **This checklist also
records BLOCKING GAPS (PREREG_TERMS_RECORD.md §2): the act cannot
execute until a design amendment adopted by the owner supplies the
missing forward terms (G-1 pick rule, G-2 interval construction,
G-3 close validity, G-4 minimum universe), the owner has ruled on
decisions D-1 (home-ice) and D-2 (OT/SO sourcing) and sequencing
item S-1, and the forward runner (F-1) is built. Preparing this
package cures none of them. Above all of it stands the Stage A
gate: Stage B does not run unless the locked home-ice v2 test
passes on Nov 30, 2026.**

## Where the sequence stands

| Stage | Act | State |
|---|---|---|
| Design + preregistration draft | PR #2839 (`NHL_SIDES_TOTALS_DESIGN.md`) | MERGED |
| MoneyPuck admission | PR #2859 | MERGED (attempt-2 input only) |
| Construction build | PR #2877 (`sportsedge/nhl_attempt2.py`, constants, 20 family tests) | MERGED — screen NOT_EXECUTABLE by design |
| Stage A (locked home-ice v2, separate construction) | Pre-lock Sep 29, 2026 | RUNNING; verdict Nov 30, 2026 — **GATES EVERYTHING BELOW** |
| Design amendment (G-1…G-4) + owner rulings (D-1, D-2, S-1) | Owner act with independent review | **NOT EXECUTED — BLOCKING** |
| Forward runner build + NON_COUNTED landing check | Finding F-1 | **NOT BUILT — act prerequisite** |
| Freeze package | This PR: README, PREREG_TERMS_RECORD, DECISIONS_AND_READINGS, this checklist, CONFIG_DRAFT.json, SPEC_HASHES.txt — all DRAFT | THIS PR (draft) |
| Freeze act | A separate future PR (contents below) | NOT EXECUTED |
| Stage B fit | On games before Dec 1, 2026, under the frozen constants, declared vintage treatment | After the act; before window pricing |
| Stage B window / one look | Dec 1, 2026 – Jan 31, 2027 / Feb 1, 2027 | NOT OPEN |

## The freeze act's contents (all in the act's one PR)

- [ ] **Stage A gate on evidence.** The Nov 30, 2026 Stage A verdict
      is PASS under the pre-lock's own act and pass line, cited in
      the freeze record — or the act does not execute and this
      construction returns to design. (Under sequencing reading S-1
      "freeze before the verdict," adopted expressly by the owner,
      this box is replaced by the record's conditional-freeze terms
      and the Stage B arming waits for the verdict.)
- [ ] **Design amendment landed first.** The amendment supplying
      G-1 (pick rule), G-2 (interval construction), G-3 (close
      validity), G-4 (minimum universe + disposition) is merged
      under its own independent review; the owner rulings on D-1
      (home-ice) and D-2 (OT/SO) are recorded with it. If D-1 takes
      Option B, the amended construction (with its declared home
      term) is what the act freezes.
- [ ] **Constants pinned on the act's head.** HALF_LIFE_GAMES,
      SHRINKAGE_PRIOR_GAMES, GOALIE_SHRINKAGE_GAMES fixed;
      DISPERSION_PHI set by the freeze fit run on the exact frozen
      head, with the build-fit reading vs residuals-around-rates
      reading adjudicated on the record; OT_HOME_WIN_SHARE /
      OT_DECISION_SHARE as ruled under D-2 (fitted values with
      their pinned computation, or the declared neutral constants).
      The constants file's STATUS flips DRAFT → FROZEN in the same
      PR; `NHL_ATTEMPT2_NOT_FROZEN` no longer refuses under the
      pinned values.
- [ ] **Config flip.** Install the family config at
      `sportsedge/forward_validation/configs/nhl_attempt2_v1.json`
      (content: this package's `CONFIG_DRAFT.json`) with exactly
      these changes: `status` DRAFT → the framework's FROZEN string
      naming the preregistration and the freeze record, and
      `prereg_draft` replaced by `prereg` + `prereg_sha256`
      (the preregistration as amended, re-verified by hash on the
      act's head). **Registry result (verified by this package,
      §Registry below): no collision — the act installs the first
      NHL registration.** The flip may also re-pin `model_version`
      to the built forward runner's sha256, and install the adopted
      amendment's own values for the fields this draft carries as
      framework defaults (min floors, missing-close share, close
      age) — **each such change is an amendment value, logged in
      the freeze record's adaptation log; any other statistical
      difference stops the act.**
- [ ] **Freeze record.** A `FREEZE_RECORD.md` for this family in
      this directory, in the NFL team-totals record's form: the
      freeze is recorded at the act PR's merge; the merge commit's
      timestamp on main is the freeze instant (no timestamp asserted
      in advance); pins recomputed on the act's head (construction/
      runner, constants, config, preregistration as amended, design,
      MoneyPuck admission, tests); the Stage B window and one look
      instantiated per the design; the k table as of the act
      (below); an adaptation log vs this package.
- [ ] **SPEC_HASHES.txt** updated in this directory: the finalized
      preregistration and constants (frozen at the act) pinned
      alongside the package pins this file already carries.
- [ ] **Evaluator pin.** Recorded in the freeze record: the Stage B
      evaluation path (the forward runner's evaluator at its pin,
      and the shared forward evaluator if the runner consumes it) —
      the Feb 1, 2027 look is computed only under the recorded pins.
      Until the act, no counted entry point for this family exists
      and no row counts.
- [ ] **Forward pricing path proven before the window opens** (a
      freeze of an un-runnable clock is a hollow act): the runner
      build's NON_COUNTED landing check reproduces the construction
      library's outputs on a historical date (construction
      equivalence), and the capture → fit → price → record path is
      demonstrated on current non-counted slates from live lane
      snapshots before Dec 1, 2026.
- [ ] **Tests green on the act's exact head:** the family's own
      suites (`tests/test_nhl_attempt2.py`,
      `tests/test_nhl_moneypuck_admission_manifest.py`, the
      runner's suite), the full suite, and both PR gates
      (dependency parity: `pyproject.toml` dev set ==
      `requirements-test.txt`; ruff
      `--select E9,F821,F822,F823,F811`).
- [ ] **Freeze-coverage gate.** The act's touched paths checked
      against `config/freeze_reconciliation_registry_v1.json`
      coverage (repo matcher) before clearance — a content-perfect
      PR can still poison main post-merge. (This package's own
      paths: checked, NOT GOVERNED — see §Registry.)
- [ ] **Readings and decisions confirmed.** R-1…R-7
      (DECISIONS_AND_READINGS.md) are confirmed as written or
      corrected in the act, and D-1 / D-2 / S-1 carry the owner's
      recorded rulings; the freeze record states the outcome for
      each. An uncorrected reading left ambiguous stops the act.

## Registry result (config collision + freeze-coverage, this package)

The registry admits exactly one config per (sport, market):
`scripts/audit_cross_sport_accuracy_readiness.py` raises
`DUPLICATE_FORWARD_MARKET_CONFIG` on any second registration (the
NBA V2 source amendment is the only authorized overlap). This
package probed the registry on current main (`aed769f75`): **there
is no NHL config in `sportsedge/forward_validation/configs/` at
all** — (NHL, MONEYLINE), (NHL, SPREAD) (the puck line's framework
name) and (NHL, TOTAL) are unclaimed among the 47 installed
configs, and installing this family's config raises no refusal
(probe: every installed config's sport/markets enumerated; zero NHL
claims). Unlike EFV2, no collision has to be resolved before the
flip. The draft config still ships inside this research package
only; it registers nothing until the act installs it.

Freeze-coverage: this package's six paths were checked with the
repo matcher (`scripts/reconcile_freeze_deltas.py::_covered_change`)
over all 11 bundles in `config/freeze_reconciliation_registry_v1.json`:
**NOT GOVERNED on every path.** The act re-checks its own (larger)
path set the same way.

## Authorization and review (the act's closing sequence)

- [ ] **Owner authorization recorded** on the act (the owner's
      ruling, or execution under the owner's standing decision
      delegation with its terms named in the freeze record — the
      NFL team-totals record's manner).
- [ ] **Independent review closes on the act's exact head** — a
      Rocky clearance naming that head, after the checks above are
      green on that head (checks count only on a head up to date
      with main under the strict ruleset).
- [ ] **Merge = the recording act.** Merge commit only; landing
      verified on the remote afterward (main == merge commit;
      config, constants and prereg blobs byte-identical to the
      cleared head). Before the merge, nothing counts; rows priced
      before it never count (no backfill). The Stage B fit then
      runs on games before Dec 1, 2026 under the frozen constants.

## Multiple-testing k at the freeze (computed by this package)

Per the Oct 22, 2026 policy (α = 0.05/k) and the NFL team-totals
freeze record's counting convention: k = the number of families
validated or under active forward test whose windows overlap this
test's window, counting this test from its freeze, conservatively —
a clock that is frozen, locked, or ruled to run and may count rows
during the window is included even if its own counting has not
started. **This test's window is Stage B: Dec 1, 2026 – Jan 31,
2027 (one look Feb 1, 2027).** Counted as of the package date
(Oct 28, 2026), from the program inventory of record
(`research/nfl_team_totals_forward_20261028/FREEZE_RECORD.md`,
k = 11 table; `research/cbb_torvik_efficiency_screen_20261028/FREEZE_ACT_CHECKLIST.md`,
k = 12 candidate table):

| # | Clock | Overlap with Dec 1, 2026 – Jan 31, 2027 |
|---|---|---|
| 1 | NFL_PROPS_PART2_FORWARD_V1 | frozen, running; NFL season window runs through Jan 2027 — overlaps |
| 2 | NFL_PROPS_PART2B_FORWARD_V1 | frozen, running — overlaps |
| 3 | NFL_PROPS_V1_1_MOVED_LINE_AMENDMENT | counted separately, conservatively (as in both prior records) — overlaps |
| 4 | NBA_PROPS_FORWARD_V1 | frozen clock; NBA season spans the window — overlaps |
| 5 | NFL_TOTALS_LEVEL_V2_FORWARD | forward leg scores Jan 13, 2027 — inside the window |
| 6 | MLB_PITCHER_PROP_PROMOTION_V2 (pitcher-K ridge) | forward clock running; counted under the program's conservative convention as applied in both prior freeze records (its accrual is seasonal — it counts no rows in Dec–Jan, and the act's recomputation may revisit this line expressly, never silently) |
| 7 | NFL_ANYTIME_TD_FORWARD_V1 (v1.1 terms) | frozen; accrual from Nov 1, 2026 slates — overlaps |
| 8 | NBA_TEAM_TOTALS_FORWARD_V1 | frozen Oct 22–23, 2026; NBA season spans the window — overlaps |
| 9 | NHL_ATTEMPT2_V1 Stage B forward test | **this test, from its freeze (the act's merge)** |

**k = 9 → α/k = 0.05/9 ≈ 0.005556.** The design's paired test is
one-sided; its significance is judged at α/k as computed here and
recomputed at the act and the verdict.

**Excluded, with reasons (the window-overlap rule applied as
written):** NFL_PASSYDS_V2_FORWARD_SCREEN — its population is 2026
weeks 8–11 and its scoring stops after four full weeks (verdict due
after Week 11, late Nov 2026), so it cannot count rows inside
Dec 1 – Jan 31; NHL home-ice v2 (Stage A) — its window is
Oct 8 – Nov 30, 2026 and its verdict lands Nov 30, 2026, the day
before this window opens. Both exclusions are named here so the
act's recomputation confronts them expressly: **if the owner counts
the Stage A gate test in this family's k, or the passyds verdict
slips into the window, k rises by one each.** The NBA props V2
configs read FROZEN but the family's recorded freeze was
quarantined by owner ruling Oct 27, 2026 and it has no active
clock — excluded, as in both prior records. All DRAFT families are
excluded until frozen.

**Conditional additions (not counted today; counted at the act if
their acts have executed):** CBB_TORVIK_EFFICIENCY_V1,
CBB_TEAM_TOTAL_DIST_V1 (the sibling CBB packages count their own
candidates the same way), NFL_ENTRY_FORM_V2 (its window is the NFL
season — overlaps), and NHL_TEAM_TOTAL_DIST_V1 if it is frozen as
its own family test inside this same window. Each executed act
raises k by one (to a package-visible maximum of 13 on the named
conditionals + exclusions above).

**k is recomputed at the freeze act and again at the Feb 1, 2027
verdict; if the counts differ, the larger governs** (the NFL
team-totals record's rule: recomputation may only raise it). The
verdict-time count will very likely exceed 9 — every family frozen
between now and Feb 1, 2027 whose window overlaps joins it.

## Standing law the act does not bend

PAPER / 0u; no wager execution; no lowered thresholds; no frozen
term of any other family touched; FAILED constructions stay retired
and this package resurrects none (attempt 1's verdict stands; the
#1249/#1253 generation stays retired); Stage A remains locked under
its own pre-lock — this family's acts never amend, consume, or
re-score it; NHL team totals are a separate family (PR #2878) with
their own protocol and gaps (G-TT-1…4) and are not part of this
package or its act; xG is never pooled across the 2025/2026 vintage
boundary except under the declared treatment
(`SINGLE_VINTAGE_ONLY:rebuilt_2026_27`); Illinois PRO teams are in
scope (the Illinois exclusion applies to college sports only);
amendments after the freeze are new versions with their own
preregistrations, scored forward only.
