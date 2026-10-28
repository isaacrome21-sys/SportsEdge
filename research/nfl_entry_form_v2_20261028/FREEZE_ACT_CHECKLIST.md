# FREEZE ACT CHECKLIST — NFL_ENTRY_FORM_V2

**Status: CHECKLIST FOR A FUTURE ACT — this document authorizes
nothing, freezes nothing, and starts no clock.** It mirrors the NFL
team-totals freeze sequence (freeze-prep PR #2858 → freeze-act PR
#2860, recorded in
`research/nfl_team_totals_forward_20261028/FREEZE_RECORD.md`): the
freeze is a separate prospective act, executed by its own PR, and is
recorded **only at that PR's merge**. The sequencing the NBA props
V2 quarantine taught binds throughout: **independent review closes
on the act's exact head BEFORE the merge records the freeze — review
first, freeze second, no exceptions.** Nothing in the freeze package
(this PR) is in force at any point.

## Where the sequence stands

| Stage | Act | State |
|---|---|---|
| Design + prereg draft | PR #2849 (DESIGN.md, PREREG_DRAFT.md, SCREEN_RESULTS.md) + Rocky design review (PR comment 6463091073) | MERGED |
| §7 build | PR #2869 (construction, constants file, evaluator adapter, fireability tests, NON_COUNTED landing check, BUILD_RECORD.md) | MERGED |
| Freeze package | This PR: PREREG_FINAL.md, this checklist, CONFIG_DRAFT.json, SPEC_HASHES.txt — all DRAFT | THIS PR (draft) |
| Freeze act | A separate future PR (contents below) | NOT EXECUTED |
| First counted slate | First NFL slate priced by the pinned construction after the act's merge (PREREG_FINAL §14; no backfill) | — |

## The freeze act's contents (all in the act's one PR)

- [ ] **Config flip.** Install the family config at
      `sportsedge/forward_validation/configs/nfl_entry_form_v2.json`
      (content: this package's `CONFIG_DRAFT.json`) with exactly two
      changes: `status` DRAFT → the framework's FROZEN string naming
      the preregistration and the freeze record, and `prereg_draft`
      replaced by `prereg` + `prereg_sha256` =
      `cfc7047caa898e624c737d3fbf4fd35e2abe8dca638c7b312c4f193f53e098ea`
      (PREREG_FINAL.md, re-verified by hash on the act's head).
      `model_version` and every gate/threshold value byte-identical
      to the draft config; the flip commit also updates any config
      binding test in the NFL team-totals manner (status assertion +
      `prereg_sha256` equality) if the act adds one.
- [ ] **REGISTRY GATE (blocking, discovered by this package).**
      The registry admits exactly one config per (sport, market):
      `scripts/audit_cross_sport_accuracy_readiness.py` raises
      `DUPLICATE_FORWARD_MARKET_CONFIG` on any second registration
      (the NBA V2 source amendment is the only authorized overlap).
      (NFL, SPREAD) and (NFL, TOTAL) are already claimed by the
      FREE_MODELS_GAME draft registrations
      (`configs/nfl_spread.json`, `configs/nfl_total.json`); this
      package verified by probe that installing the EFV2 config
      beside them refuses with `DUPLICATE_FORWARD_MARKET_CONFIG:NFL:SPREAD`.
      **The act must resolve the collision lawfully before the
      flip** — retire/supersede those two draft registrations for
      these markets, or amend the audit under governance. Landing
      both registrations, renaming EFV2's markets to dodge the key,
      or weakening the audit silently are all prohibited.
- [ ] **Freeze record.** A `FREEZE_RECORD.md` for this family in
      this directory, in the NFL team-totals record's form: the
      freeze is recorded at the act PR's merge; the merge commit's
      timestamp on main is the freeze instant (no timestamp asserted
      in advance); pins recomputed on the act's head (construction,
      constants, adapter, config, prereg, Lane A pair, tests,
      fitted-constants record); the first counted slate instantiated
      per PREREG_FINAL §14; the k table as of the act (below); an
      adaptation log vs this package (expected: status/pins only —
      any statistical difference stops the act).
- [ ] **SPEC_HASHES.txt** updated in this directory: the finalized
      preregistration (frozen at the act) pinned alongside the
      package pins this file already carries.
- [ ] **Evaluator pin.** Recorded in the freeze record: the shared
      forward evaluator at an exact commit + this family's adapter
      at its PREREG_FINAL §10 pin. Until the act, every counted entry
      point raises `EF_V2_FREEZE_NOT_AUTHORIZED`; counted evaluation
      is authorized only under the recorded pin and the FROZEN
      config. No caller-controlled bypass exists in the adapter and
      none may be added by the act.
- [ ] **Constants verification.** The constants file on the act's
      head hashes to the PREREG_FINAL §10 pin
      (`cee85fcedb…`); the §11 freeze-fit values on the act's head
      are the values recorded there. A re-fit producing different
      bytes stops the act (package amendment + re-review first).
- [ ] **Tests green on the act's exact head:** the family's own
      suites (`tests/test_nfl_entry_form_v2.py`,
      `tests/test_nfl_entry_form_v2_evaluator.py` — including the
      §3 fireability assertions at the pinned σ), the full suite,
      and both PR gates (dependency parity:
      `pyproject.toml` dev set == `requirements-test.txt`; ruff
      `--select E9,F821,F822,F823,F811`).
- [ ] **Freeze-coverage gate.** The act's touched paths checked
      against `config/freeze_reconciliation_registry_v1.json`
      coverage (repo matcher) before clearance — a content-perfect
      PR can still poison main post-merge.
- [ ] **Live pricing path proven before the first eligible slate**
      (the NFL team-totals act's hard gate: a freeze of an
      un-runnable clock is a hollow act). The build's NON_COUNTED
      landing check (2025 Week 10) is on file; before the first
      eligible slate the capture → price → record path must be
      demonstrated on a current, non-counted slate from live lane
      snapshots, and the run-record fields the adapter needs
      (entry snapshot, personnel state, Lane A emissions per §5.6a)
      verified present per row.
- [ ] **Readings pinned.** PREREG_FINAL §12's four readings are
      confirmed as written or corrected by Rocky/owner in the act;
      the freeze record states the outcome for each. An uncorrected
      reading left ambiguous stops the act.

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
      config and prereg blobs byte-identical to the cleared head).
      Before the merge, nothing counts; rows priced before it never
      count (no backfill).

## Multiple-testing k at the freeze (computed by this package)

Per the Oct 22, 2026 policy and PREREG_FINAL's multiple-testing
framing (§5.3's sign test and PLAY eligibility judge at α = 0.05/k):
k = the number of families validated or under active forward test
whose windows overlap this test's window, counting this test from
its freeze, conservatively — a clock that is frozen, locked, or
ruled to run and may count rows during the window is included even
if its own counting has not started (the NBA team-totals freeze
record's manner, carried into the NFL team-totals record's table).

The NFL team-totals freeze record (Oct 28, 2026) counted **k = 11**
including itself. Its table carries forward unchanged — no clock on
it has closed, and nothing merged since adds a frozen forward test
(the CBB admissions and screens are design-stage, not frozen clocks;
the NBA props V2 configs read FROZEN but the family's recorded
freeze was quarantined by owner ruling Oct 27, 2026 and it has no
active clock — excluded there, excluded here). Adding this family:

| # | Clock | State (source: NFL team-totals FREEZE_RECORD, Oct 28, 2026) |
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
| 12 | NFL_ENTRY_FORM_V2 forward test | **this test, from its freeze (the act's merge)** |

**k = 12 → α/k = 0.05/12 ≈ 0.004167; two-sided intervals at
1 − α/k ≈ 99.583% where the policy applies.** Sources:
`research/nfl_team_totals_forward_20261028/FREEZE_RECORD.md`
(the k = 11 table and its counting convention);
`research/nba_team_totals_forward_20261022/FREEZE_RECORD.md` (the
convention's origin); config states on main at this package
(FROZEN: the NBA props V1 family configs, `nfl_team_total.json`;
NBA props V2 configs FROZEN-labeled but quarantined — see above).
**k is recomputed at the freeze act and again at any verdict; if
the counts differ, the larger governs.**

## Standing law the act does not bend

PAPER / 0u; no wager execution; no lowered thresholds; no frozen
term of any other family touched (§9 non-interference — Part 2/2B,
ATD v1.1, the passyds v2 screen, and the NFL team-totals clock run
untouched); FAILED constructions stay retired and this package
resurrects none; amendments after the freeze are new versions with
their own preregistrations, scored forward only.
