# FREEZE ACT CHECKLIST — CBB_TORVIK_EFFICIENCY_V1

**Status: CHECKLIST FOR A FUTURE ACT — this document authorizes
nothing, freezes nothing, and starts no clock.** It mirrors the
NFL team-totals freeze sequence (freeze-prep PR #2858 →
freeze-act PR #2860) and the EFV2 freeze package (PR #2884): the
freeze is a separate prospective act, executed by its own PR,
and is recorded **only at that PR's merge**. The sequencing the
NBA props V2 quarantine taught binds throughout: **independent
review closes on the act's exact head BEFORE the merge records
the freeze — review first, freeze second, no exceptions.**
Nothing in the freeze package (this PR) is in force at any
point. **This checklist also records three BLOCKING GAPS
(PREREG_FINAL §8): the act cannot execute until a design
amendment supplies the missing forward terms (pick rule,
interval construction, close-validity rule) under its own
review. Preparing this package does not cure them.**

## Where the sequence stands

| Stage | Act | State |
|---|---|---|
| Design + prereg draft (§5 terms) | PR #2843 (`CBB_SIDES_TOTALS_DESIGN_AND_PREREG_DRAFT.md`) | MERGED |
| Amendment 1 (prior-snapshot convention, screen) | PR #2883 | MERGED |
| Design screen attempt 4 — DESIGN_PASS | PR #2891 (marginal spread-vs-simple leg disclosed in PREREG_FINAL) | MERGED |
| Identity crosswalk | PR #2898 | MERGED (on main) |
| Live Torvik route admission | PR #2841 + daily pull job (late-pull guard applied) | MERGED / RUNNING |
| Capture gate (iii) | `cbb-capture-landing-precheck-20261101`, Sun Nov 1 07:00 CT + opening-slate receipts | **OPEN — act waits for it** |
| Design amendment (gaps G-1/G-2/G-3) | Owner act with independent review | **NOT EXECUTED — BLOCKING** |
| Forward runner build + NON_COUNTED landing check | New module implementing design §1 on the live route (finding F-1) | **NOT BUILT — act prerequisite** |
| Freeze package | This PR: PREREG_FINAL.md, this checklist, CONFIG_DRAFT.json, SPEC_HASHES.txt — all DRAFT | THIS PR (draft) |
| Freeze act | A separate future PR (contents below) | NOT EXECUTED |
| First counted slate | First slate priced by the pinned forward runner after the act's merge; §5 floor: Nov 2, 2026 at the earliest; no backfill | — |

## The freeze act's contents (all in the act's one PR)

- [ ] **Design amendment landed first.** The amendment
      supplying G-1 (pick rule), G-2 (interval construction)
      and G-3 (close-validity / missing-close rule) is merged
      under its own independent review, and PREREG_FINAL is
      re-issued against it (new package PR; this package's
      transcription is not edited in place after clearance).
- [ ] **Capture gate (iii) closed on evidence:** the Nov 1
      pre-check report plus five-stage delivery receipts for
      the opening slates, on file.
- [ ] **Config flip.** Install the family config at
      `sportsedge/forward_validation/configs/cbb_torvik_efficiency_v1.json`
      (content: this package's `CONFIG_DRAFT.json`) with exactly
      these changes: `status` DRAFT → the framework's FROZEN
      string naming the preregistration and the freeze record,
      and `prereg_draft` replaced by `prereg` + `prereg_sha256`
      (PREREG_FINAL.md as re-issued, re-verified by hash on the
      act's head). **Registry result (verified by this package,
      §Registry below): no collision — the act installs the
      first CBB registration.** The flip may also re-pin
      `model_version` to the built forward runner's sha256
      (a pin change, logged in the freeze record's adaptation
      log); **every gate/threshold value stays byte-identical
      to the draft config — any statistical difference stops
      the act.**
- [ ] **Freeze record.** A `FREEZE_RECORD.md` for this family
      in this directory, in the NFL team-totals record's form:
      the freeze is recorded at the act PR's merge; the merge
      commit's timestamp on main is the freeze instant (no
      timestamp asserted in advance); pins recomputed on the
      act's head (construction/runner, config, prereg, design,
      crosswalk, capture-scope module, tests); the first
      counted slate instantiated per PREREG_FINAL §5; the k
      table as of the act (below); the seed instantiated
      (20261028); an adaptation log vs this package (expected:
      status/pins only, plus the design amendment's terms —
      any other statistical difference stops the act).
- [ ] **SPEC_HASHES.txt** updated in this directory: the
      finalized preregistration (frozen at the act) pinned
      alongside the package pins this file already carries.
- [ ] **Evaluator pin.** Recorded in the freeze record: the
      shared forward evaluator at an exact commit + the built
      forward runner at its pin. Counted evaluation is
      authorized only under the recorded pins and the FROZEN
      config; until the act, no counted entry point for this
      family exists and no row counts.
- [ ] **Forward pricing path proven before the first eligible
      slate** (a freeze of an un-runnable clock is a hollow
      act): the runner build's NON_COUNTED landing check
      reproduces the screen runner's outputs on a historical
      date (construction equivalence), and the capture → price
      → record path is demonstrated on a current, non-counted
      slate from live lane snapshots before the first counted
      slate.
- [ ] **Tests green on the act's exact head:** the family's
      own suites (`tests/test_cbb_torvik_screen_attempt4.py`,
      `tests/test_cbb_team_totals.py`,
      `tests/test_cbb_identity_crosswalk.py`,
      `tests/test_cbb_capture_scope_nov1.py`), the full suite,
      and both PR gates (dependency parity: `pyproject.toml`
      dev set == `requirements-test.txt`; ruff
      `--select E9,F821,F822,F823,F811`).
- [ ] **Freeze-coverage gate.** The act's touched paths checked
      against `config/freeze_reconciliation_registry_v1.json`
      coverage (repo matcher) before clearance — a
      content-perfect PR can still poison main post-merge.
      (This package's own paths: checked, NOT GOVERNED.)
- [ ] **Readings confirmed.** PREREG_FINAL's R-1 and A-1/A-2
      are confirmed as written or corrected by Rocky/owner in
      the act; the freeze record states the outcome for each.
      An uncorrected reading left ambiguous stops the act.

## Registry result (config collision check, this package)

The registry admits exactly one config per (sport, market):
`scripts/audit_cross_sport_accuracy_readiness.py` raises
`DUPLICATE_FORWARD_MARKET_CONFIG` on any second registration
(the NBA V2 source amendment is the only authorized overlap).
This package probed the registry on current main the way the
EFV2 package found its (NFL, SPREAD) collision: **there is no
CBB config in `sportsedge/forward_validation/configs/` at all**
— (CBB, SPREAD) and (CBB, TOTAL) are unclaimed, and installing
this family's config beside the existing 47 configs raises no
refusal (probe result recorded in the PR body). Unlike EFV2,
no collision has to be resolved before the flip. The draft
config still ships inside this research package only; it
registers nothing until the act installs it.

## Authorization and review (the act's closing sequence)

- [ ] **Owner authorization recorded** on the act (the owner's
      ruling, or execution under the owner's standing decision
      delegation with its terms named in the freeze record —
      the NFL team-totals record's manner).
- [ ] **Independent review closes on the act's exact head** —
      a Rocky clearance naming that head, after the checks
      above are green on that head (checks count only on a
      head up to date with main under the strict ruleset).
- [ ] **Merge = the recording act.** Merge commit only;
      landing verified on the remote afterward (main == merge
      commit; config and prereg blobs byte-identical to the
      cleared head). Before the merge, nothing counts; rows
      priced before it never count (no backfill).

## Multiple-testing k at the freeze (computed by this package)

Per the Oct 22, 2026 policy (α = 0.05/k) and the NFL
team-totals freeze record's counting convention: k = the number
of families validated or under active forward test whose
windows overlap this test's window, counting this test from its
freeze, conservatively — a clock that is frozen, locked, or
ruled to run and may count rows during the window is included
even if its own counting has not started.

| # | Clock | State |
|---|---|---|
| 1 | NFL_PROPS_PART2_FORWARD_V1 | frozen, running |
| 2 | NFL_PROPS_PART2B_FORWARD_V1 | frozen, running |
| 3 | NFL_PROPS_V1_1_MOVED_LINE_AMENDMENT | counted separately, conservatively |
| 4 | NBA_PROPS_FORWARD_V1 | frozen clock |
| 5 | NFL_TOTALS_LEVEL_V2_FORWARD | forward leg scores Jan 13, 2027 — window overlaps |
| 6 | MLB_PITCHER_PROP_PROMOTION_V2 (pitcher-K ridge) | forward clock running |
| 7 | NFL_ANYTIME_TD_FORWARD_V1 (v1.1 terms) | frozen; accrual from Nov 1, 2026 slates |
| 8 | NFL_PASSYDS_V2_FORWARD_SCREEN | forward screen; population opened Oct 29, 2026 |
| 9 | NBA_TEAM_TOTALS_FORWARD_V1 | frozen Oct 22–23, 2026; armed, not yet counting |
| 10 | NHL home-ice v2 (Stage A accuracy verdict) | locked forward test; verdict Nov 30, 2026 |
| 11 | NFL_TEAM_TOTAL_DIST_V1 forward test | frozen Oct 28, 2026 (PR #2860) |
| 12 | CBB_TORVIK_EFFICIENCY_V1 forward test | **this test, from its freeze (the act's merge)** |

**k = 12 → α/k = 0.05/12 ≈ 0.004167; two-sided intervals at
1 − α/k ≈ 99.583% where the multiple-testing policy applies.**
Sources: `research/nfl_team_totals_forward_20261028/FREEZE_RECORD.md`
(the k = 11 table and its counting convention, carried forward
unchanged — no clock on it has closed);
`research/nfl_entry_form_v2_20261028/FREEZE_ACT_CHECKLIST.md`
(the same table extended by that family's package to k = 12 for
its own candidate; that family's act has NOT executed, so it is
not counted here). The NBA props V2 configs read FROZEN but the
family's recorded freeze was quarantined by owner ruling Oct 27,
2026 and it has no active clock — excluded there, excluded here.
**Sensitivity, stated now so the act cannot discover it late:**
this package's sibling CBB freeze package (prepared concurrently)
counts its own candidate the same way; if the sibling act — or
the NFL_ENTRY_FORM_V2 act — executes before this family's act or
verdict, k rises by one per executed act (13, then 14).
**k is recomputed at the freeze act and again at the verdict;
if the counts differ, the larger governs** (the NFL team-totals
record's rule: recomputation may only raise it).

## Standing law the act does not bend

PAPER / 0u; no wager execution; no lowered thresholds; no
frozen term of any other family touched; FAILED constructions
stay retired and this package resurrects none; CBB first-half
lines are a separate family (its PBP prerequisite was admitted
in PR #2901 but its screen has NOT run) and are not part of
this package or its act; Illinois PRO teams are in scope,
Illinois COLLEGE teams are excluded fail-closed; amendments
after the freeze are new versions with their own
preregistrations, scored forward only.
