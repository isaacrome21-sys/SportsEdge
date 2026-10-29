# FREEZE RECORD — NFL_ENTRY_FORM_V2 Forward Test

**Status: PREPARED FREEZE ACT — DRAFT ONLY. THE FREEZE EXECUTES
ONLY ON ISAAC'S PROSPECTIVE OWNER ACT.** This record is carried by
the freeze-act pull request (branch `rocky/efv2-freeze-act-20261028`,
prepared Oct 28, 2026) as a **draft** for independent exact-head
review. **The freeze is recorded only at that PR's merge, and the
merge itself executes only on Isaac's prospective owner
authorization recorded in chat. Before that merge, nothing in this
package is in force: the config flip committed on the act branch is
not counting, no clock has started, and no slate counts. The freeze
takes effect only at the merge — never at commit, push, or review.**
Independent review closes on the freeze act's exact head BEFORE the
merge records the freeze (the sequencing the NBA props V2
quarantine taught: review first, freeze second, no exceptions).

- Freeze timestamp: **recorded at merge of the freeze-act PR** (the
  merge commit's timestamp on main is the freeze instant; no
  timestamp is asserted in advance).
- Document: `research/nfl_entry_form_v2_20261028/PREREG_FINAL.md`
- This family's frozen preregistration sha256:
  `cfc7047caa898e624c737d3fbf4fd35e2abe8dca638c7b312c4f193f53e098ea`
  (re-verified by hash on the act's head at preparation).
- Design origin: PR #2849 (DESIGN.md, PREREG_DRAFT.md,
  SCREEN_RESULTS.md) + Rocky design review (PR comment 6463091073);
  §7 build PR #2869; freeze package PR #2884
  (PREREG_FINAL.md, FREEZE_ACT_CHECKLIST.md, CONFIG_DRAFT.json,
  SPEC_HASHES.txt); registry-collision resolution PR #2902
  (COLLISION_RESOLUTION_MEMO.md).
- Authority: **OPEN — owner authorization not yet recorded.** This
  preparation executes nothing; the act closes only when Isaac's
  prospective authorization is recorded in chat and independent
  review has closed on the act's exact head (see OPEN ITEMS).

## Registry gate — discharged inside this act

The forward-validation registry admits exactly one config per
(sport, market); (NFL, SPREAD) and (NFL, TOTAL) were claimed by the
FREE_MODELS_GAME draft registrations `configs/nfl_spread.json` and
`configs/nfl_total.json`. Per COLLISION_RESOLUTION_MEMO.md Option A,
this act retires those two draft registrations **first** (act
commit 1: `REGISTRY_RETIREMENT_RECORD.md` in this directory, which
restates the evidence — both DRAFT — NOT FROZEN, one commit each,
zero countable rows by their own terms, no verdict record carrying
either sha256, no code loading either file — together with both
sha256s, and deletes the two files), and only then performs the
config flip (act commit 2). No state of main ever holds both
registrations or neither.

## Pins (sha256, recomputed at preparation on the act's head)

| Artifact | sha256 |
|---|---|
| Construction `sportsedge/nfl_entry_form_v2.py` | `5febc4e74df32e1ad2bf4e2e8b74f65c677e7564ef0d02071d6e90c2f99627b9` |
| Constants file `sportsedge/nfl_entry_form_v2_constants.py` | `cee85fcedb848e43eded5b64477c6d9d0a197d45e22e7de80286f2207fa8d603` |
| Evaluator adapter `sportsedge/nfl_entry_form_v2_evaluator.py` | `d547a436eb93d739beae3c06e1397fa0855cc6fa23dfb88dbaf96e30741b36f0` |
| Shared forward evaluator `sportsedge/forward_validation/core.py` | `f6ad4bf2220d07b6ab960924a48b4aa886c8a9f1e79cb431307de50f7ef002f2` |
| Framework config `sportsedge/forward_validation/configs/nfl_entry_form_v2.json` (as flipped by this act) | `d2cb5bcf463fa711c592b0583411867154ecc543716f15515612d4ae0e392b30` |
| Preregistration (frozen at the act) `PREREG_FINAL.md` | `cfc7047caa898e624c737d3fbf4fd35e2abe8dca638c7b312c4f193f53e098ea` |
| Fitted constants record `fitted_constants.json` | `a0ed28241648a98c7b6b7ee9e7166b04964a6914b5abb65765c06a230ee02820` |
| Construction tests `tests/test_nfl_entry_form_v2.py` | `4cff1e4549109848500e86c42c8041aeed062b030f97da408ef0c48345159be5` |
| Evaluator tests `tests/test_nfl_entry_form_v2_evaluator.py` | `741b23618d447d7f927c69c2aa94ab3ba65c7b17aec1ae61665337c6815ba474` |
| Lane A `artifacts/free_models.py` (§5.6a baseline) | `a8abf4606acafd2405ec037ea3bf69f1a6a5168baa4750631cc0fbebcece1fa3` |
| Lane A root shim `free_models.py` | `9160bbd3fd02147875942a709d2793e001281886a0969758acbcfdadf4356f67` |
| Full pin list | `SPEC_HASHES.txt` in this package (updated by this act) |

The config's `model_version` is the pin string
`nfl_entry_form_v2@sha256:5febc4e74df32e1ad2bf4e2e8b74f65c677e7564ef0d02071d6e90c2f99627b9`
— **unchanged from the freeze package's CONFIG_DRAFT.json and equal
to the construction file's sha256 on the act's head**: any change
to the construction file breaks the pin until it is re-struck
under a new version by a governed act.

## Evaluator pin

Recorded here per PREREG_FINAL §7.6/§14: the shared forward
evaluator `sportsedge/forward_validation/core.py` (sha256
`f6ad4bf2…` above) at the freeze-act PR's merge commit, plus this
family's adapter `sportsedge/nfl_entry_form_v2_evaluator.py` at its
§10 pin (`d547a436…`). Until the act merges, every counted entry
point of the adapter raises `EF_V2_FREEZE_NOT_AUTHORIZED`; counted
evaluation is authorized only under this recorded pin and the
FROZEN config, and only for rows priced after the merge. No
caller-controlled bypass exists in the adapter and none is added
by this act.

## Constants verification

The constants file on the act's head hashes to the PREREG_FINAL
§10 pin (`cee85fcedb…`, table above) and the §11 freeze-fit values
on the act's head are the values recorded there — one pooled OLS
fit on the 1,327 eligible 2020–2025 design rows, fitted once:
fitted HFA 1.8157; σ_fit SPREAD 14.0347 / TOTAL 13.7368 (floor
12.5, not binding); the §3 fireability assertions at the pinned σ
are unit-tested in `tests/test_nfl_entry_form_v2.py`. No re-fit was
performed at this act; a re-fit producing different bytes would
stop the act (package amendment + re-review first).

## Construction identity

`NFL_ENTRY_FORM_V2`: a market-blind EPA core (prior games only,
250-play shrinkage, 0.30 prior-season carry) with form divergence,
per-market OLS mappings fitted once on design data, and a
residual-agreement path used as a sign veto only; probabilities
Φ(|d|/σ) with no market anchoring; QB starter state must be KNOWN
at pricing or the row passes (PREREG_FINAL §3). The claim under
test is relocated honestly: every beat-the-close architecture was
falsified by the design screens, so the family is judged forward on
entry-snapshot CLV/ROI under the preregistration's six per-market
criteria. DESIGN DATA — ZERO VALIDATION CREDIT attaches to the
design screens (PREREG_FINAL §7.5), and §13's annotation stands:
the §4.2 agreement evidence was measured at closes; no entry-line
measurement exists, and nothing in this act changes that.

## Forward-test terms (from the frozen preregistration, copied terms)

- **Markets:** NFL spread and game total, gated **separately** —
  each market has its own picks, its own §5 verdict, and its own
  §6 kills. Moneyline is out of scope.
- **Pass criteria (§5, per market, ALL required):** ≥ 40 graded
  picks in the window; ROI > 0 at captured DK entry prices; mean
  CLV > 0 on same-line rows under the §8 close rule **and** the
  §8 second test passes (adverse moves do not significantly
  outnumber favorable ones — one-sided sign test, judged at
  α = 0.05/k under the multiple-testing policy) **and** the
  coverage label is not LOW_COVERAGE-only **and** the
  INSUFFICIENT_CLOSE_DATA trip has not fired; the §5.4 band
  calibration battery; full-slate MAE ≤ the closing line's MAE +
  0.25 pts; **and** both baselines beaten (§5.6: Lane A on
  identical priced games under the identical pick rule, and the
  contemporaneous market baseline jointly via §5.2 + §5.3 + §5.5).
  Anything short of all six is not verified — no partial credit.
- **Kill criteria (§6, per market, fail fast):** calibration kill,
  CLV kill (mean same-line CLV ≤ −0.50 pts at ≥ 30 graded picks —
  READING 2 units), accuracy kill (MAE gap > 1.0 pt at ≥ 40 priced
  games; disclosed in the preregistration as expected to be live
  from the first checkpoint), coverage kill (> 20% true capture
  failures), integrity kill (fail closed, no threshold).
- **Close rule (§8 = the Oct 22, 2026 v1.1 amendment, unchanged):**
  LINE_MOVED rows form a separate bucket with direction recorded
  (READING 3 convention), no repricing; the moved bucket is a
  second verdict test; the 20% trip counts only the four true
  capture failures; moved rows > 50% of a market → LOW_COVERAGE,
  which cannot open PLAY by itself.
- **Window:** freeze → end of the 2026 REG season; a market with
  < 40 graded picks at window end extends through 2027 Week 6
  (REG). The verdict review happens **once**, at window close or
  when a §6 kill fires; checkpoints report counts/CLV/ROI/coverage
  without verdict language (anti-peeking).
- **Seed:** 20261028, recorded at this act (the program's binding
  seed convention, per the NFL team-totals freeze record's
  manner).
- **Registration:** research-only (`REGISTERED_RESEARCH_ONLY`),
  `verified_play = false`, PAPER / 0u. A pass under this test
  changes no registration or eligibility by itself.

## First counted slate (prospective — named by rule, never by a past date)

**The first NFL slate priced by the pinned construction after
this freeze act is recorded (the act PR's merge).** Operatively
per PREREG_FINAL §4/§14: the validation split is every population
game with kickoff strictly after the freeze commit's timestamp;
the first eligible slate is the **first Sunday slate with ≥ 8
captured games whose entry snapshots all post strictly after the
freeze timestamp and after the §7 landing check passes**. Rows
priced before the merge never count — no backfill; 2026 games
played before the freeze are excluded forever. No §5/§6 metric is
computed on any forward row before the first counted slate.

## α = 0.05/k — k recomputed at this act

Per the Oct 22, 2026 policy and PREREG_FINAL's multiple-testing
framing: k = the number of families validated or under active
forward test whose windows overlap this test's window, counting
this test from its freeze, conservatively (a clock that is frozen,
locked, or ruled to run and may count rows during the window is
included even if its own counting has not started — the NBA
team-totals freeze record's manner). The freeze package (PR #2884)
computed **k = 12** on the NFL team-totals record's k = 11 table
plus this family. **Recomputed at this act's preparation on its
base head: unchanged — k = 12.** Nothing merged since the package
adds a frozen forward test (the CBB packages are design-stage; the
PR #2915 MLB batter record is a FAILED_SCREEN, not a clock; the
NFL period prereg is a draft), and no clock on the table has
closed.

| # | Clock | State as of this act |
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
1 − α/k ≈ 99.583% where the policy applies. k is recomputed at
the verdict review; if the freeze and review counts differ, the
larger governs.** Excluded, with reason: NBA_PROPS_V2 — its
recorded freeze was quarantined by owner ruling (Oct 27, 2026)
and it has no active clock.

## §12 readings — outcome at this act

PREREG_FINAL §12 carries four readings as FREEZE PACKAGE
PROPOSALS, open to Rocky/owner correction before the act. This
preparation proposes **no correction**; each is carried as written:

- **READING 1 — fit shape:** one pooled fit on 2020–2025 design
  data, fitted once (§7.4 governs over DESIGN §4.1's
  parenthetical). Carried as written.
- **READING 2 — §6.2 CLV-kill units:** −0.50 pts read as −0.0050
  no-vig probability points (the only consistent reading).
  Carried as written.
- **READING 3 — §8 moved-row direction:** favorable = the close
  moved toward the picked side (NBA team-totals §6c convention,
  generalized to spreads). Carried as written.
- **READING 4 — two constants from the reference implementation:**
  QB-delta attempt scale 36 and pace-deviation center 124.0, taken
  verbatim from `design_screen.py` and cited in the pinned
  constants file. Carried as written.

Final confirmation of the readings is part of the act's closing
sequence (owner authorization + independent review on the exact
head) and remains an OPEN item below until that sequence runs; no
reading is left ambiguous in the interim — the preregistration's
§§1–9 stand as written and no reading changes any term.

## Adaptation log (vs the freeze package, PR #2884)

- **Registry retirement added** as act step 1
  (`REGISTRY_RETIREMENT_RECORD.md` + deletion of the two
  FREE_MODELS_GAME draft configs), per PR #2902's recommended
  path. The package carried the collision as a blocking item; the
  memo resolved it on paper; this act executes the resolution
  inside its own PR, sequenced before the flip.
- **Config:** installed at
  `sportsedge/forward_validation/configs/nfl_entry_form_v2.json`
  from the package's `CONFIG_DRAFT.json` with exactly the two
  checklist changes — `status` DRAFT → the FROZEN string naming
  the preregistration and this record; `prereg_draft` replaced by
  `prereg` + `prereg_sha256` (the PREREG_FINAL pin, re-verified on
  the act's head). `model_version` and every gate/threshold value
  are identical to the draft config (verified by diff at
  preparation: the changed keys are exactly `status`, `prereg`,
  `prereg_sha256` in place of `prereg_draft`).
- **SPEC_HASHES.txt:** the package pins stand unchanged; this act
  appends pins for `FREEZE_RECORD.md`,
  `REGISTRY_RETIREMENT_RECORD.md`, and the installed framework
  config.
- **k:** package's k = 12 recomputed at the act — unchanged (see
  the k section). The retirement does not affect k: the retired
  drafts were never clocks.
- **Config binding test:** none added. No config binding test
  exists for this family to update (the family suites carry no
  config references — verified at preparation), and the checklist
  requires one only if the act adds one.
- **Audit-suite census scope (act readiness fix):** the two
  readiness-audit suites
  (`tests/test_cross_sport_accuracy_readiness.py`,
  `tests/test_nba_v2_accuracy_readiness_bridge_20261026.py`) each
  carry a census asserting exactly four `*_v2.json` configs
  program-wide — written when the only such files were the four
  NBA props V2 configs. Installing this family's config
  (`nfl_entry_form_v2.json`, also `*_v2.json`) made the count 5
  and failed both suites on the act head (verified: both pass on
  the act's base, both failed on the act head before this fix).
  The act scopes each census to its intended subject — the NBA
  V2 family (`sport == "NBA"`, matching the bridge suite's own
  `nba_player_*_v2.json` pin loop) — changing no assertion's
  subject, count, or strength: a fifth NBA `*_v2.json` config
  would still fail the census. No other test content changed.
- **Statistical terms:** no difference from the package — any
  statistical difference would stop the act.

## OPEN ITEMS — what this preparation deliberately does not close

- [ ] **Owner authorization (OPEN).** The freeze executes only on
      Isaac's prospective owner authorization recorded in chat.
      This draft PR must not be merged without it.
- [ ] **Independent review on the act's exact head (OPEN).** A
      Rocky clearance naming the final head, after the readiness
      audit and checks are green on that head (checks count only
      on a head up to date with main under the strict ruleset).
- [ ] **Merge = the recording act (OPEN).** Merge commit only;
      landing verified on the remote afterward (main == merge
      commit; config and prereg blobs byte-identical to the
      cleared head).
- [ ] **Live pricing path demonstration (OPEN — due after merge,
      before the first eligible slate).** The build's NON_COUNTED
      landing check (2025 Week 10) is on file in this directory.
      Per FREEZE_ACT_CHECKLIST.md and PREREG_FINAL §7.8/§14, the
      capture → price → record path must be demonstrated on a
      current, non-counted slate from live lane snapshots, with
      the run-record fields the adapter needs (entry snapshot,
      personnel state, Lane A emissions per §5.6a) verified present
      per row, **before** the first eligible slate. This cannot be
      completed inside the preparation and is not faked here.
- [ ] **§12 readings final confirmation (OPEN).** Carried as
      written above; confirmation (or correction) is recorded in
      the act's closing sequence.

## Standing law this act does not bend

PAPER / 0u; no wager execution; no lowered thresholds; no frozen
term of any other family touched (PREREG_FINAL §9
non-interference — Part 2/2B, ATD v1.1, the passing-yards v2
screen, and the NFL team-totals clock run untouched); FAILED
constructions stay retired and this act resurrects none;
amendments after the freeze are new versions with their own
preregistrations, scored forward only.

*Freeze record prepared Oct 28, 2026. The freeze is recorded at
the merge of the freeze-act PR, on Isaac's prospective owner
authorization; before that merge, nothing here is in force.*
