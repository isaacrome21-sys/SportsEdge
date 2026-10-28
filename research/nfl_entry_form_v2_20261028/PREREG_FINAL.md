# PREREGISTRATION — NFL_ENTRY_FORM_V2 (NFL spread & game total)

**Status: FINAL DRAFT — FREEZE PACKAGE, NOT FROZEN. This document
starts no clock, counts no rows, and authorizes no picks.** It is the
finalized preregistration text prepared for the freeze act; it becomes
a preregistration in force only when the freeze act executes as
`FREEZE_ACT_CHECKLIST.md` (this directory) specifies: (a) independent
review has closed on the exact head carrying the freeze act,
(b) the owner authorization is recorded, (c) the family config flips
DRAFT → FROZEN as part of that act, and (d) the act's merge to main
records the freeze — never a commit, push, or review in this package.
Until that merge, the family's label is **DESIGN ONLY**,
`verified_play = false`, PAPER / 0u, and its rows — if a research card
shows them at all — display as LEAN "unvalidated estimate".

**Provenance:** finalized from `PREREG_DRAFT.md` in this directory
(sha256 `8fc90394d47cb7f30656f282e8bc27dee90acb46d72115b066374ad6ead40616`,
merged in PR #2849; §7 build merged in PR #2869) at main `a61fe0029`.
§§1–9 below are the draft's text **verbatim** — no statistical term,
threshold, pass criterion, kill criterion, or rule differs from the
draft. Finalization adds only: this status/provenance block, the pins
(§10), the recorded freeze-fit values (§11), four labeled readings of
the build (§12), the §4.2 evidence annotation (§13), and the
first-counted-slate statement (§14).

**Construction:** `NFL_ENTRY_FORM_V2`, specified in `DESIGN.md` in this
directory (sha256 pinned at freeze). Design evidence: `SCREEN_RESULTS.md`
in this directory — labeled DESIGN, zero validation credit, and containing
**negative** results against the closing line that this preregistration
does not hide: the construction's claim (§2) is about the entry line and
is testable only in the validation split defined here.

**Verified, as this preregistration uses the word** (owner ruling, Oct 27,
2026, repealing the 50-graded-picks gate): a market is VERIFIED when this
preregistration's chronological out-of-sample validation **passes in
full** against BOTH baselines (§5.6) — the existing model (Lane A
`free_models.py` at the freeze commit) and the contemporaneous market
baseline (captured DraftKings lines). Forward grading (CLV/ROI reporting)
continues after any verdict per standing law; it is the passage of §5,
not a pick count, that carries the label. PLAY eligibility additionally
faces the program's multiple-testing policy (primary test at α = 0.05/k,
k = the number of validated families on the verdict date).

---

## 1. Markets and gating

NFL spread and NFL game total, gated **separately**: each market has its
own projection mapping, its own picks, its own §5 verdict, and its own §6
kills. A verdict or kill in one market says nothing about the other.
Moneyline is out of scope.

## 2. The claim under test

At the DraftKings entry snapshot (the lines lane's T-1H write), the
construction's projection — computed from the confirmed personnel state
and current-form EPA at that moment — disagrees with the entry line in
ways that earn **positive CLV** (the captured close moves toward the
disagreement) and **positive ROI at captured entry prices**, when the
picks are restricted to games where the independent residual-agreement
path concurs in sign (§3). The construction claims nothing against the
closing line itself; the design screens record that claim as falsified
for every architecture tested, including this one's core.

## 3. Construction (frozen at freeze; summary — DESIGN.md §4 governs)

- **Projection core:** off/def EPA/play, season window shrunk (prior 250
  plays, prior-season carry 0.30), last-4 form blend (150-play shrink to
  season rate); score means via (off − def) × expected plays; fitted HFA;
  per-market OLS mapping fitted **once at freeze on 2020–2025 design
  data** (margin: EPA margin + form divergence; total: EPA total + form
  divergence). No refit during validation, for any reason.
- **Residual-agreement path:** per-market OLS on the market residual from
  the frozen context feature set (DESIGN.md §4.2), fitted once at freeze
  on design data. Used **only** as a sign-agreement veto.
- **Probability:** `p = Φ(|d| / σ_fit)`, `d` = projection − entry line,
  **raw and uncapped**; σ fitted once at freeze on design residuals with
  floor **12.5** per market. (Design-stage fitted values: margin 14.40,
  totals 13.95 — the freeze fit governs.)
- **Pick rule (at the entry snapshot, no discretion):** PICK iff
  sign(adj) == sign(d) AND |d| ≥ 3.0 AND p ≥ 0.545 AND picked-side DK
  price ≥ −165 AND both teams have ≥ 3 prior REG games this season AND
  both teams' starting-QB states are known from the pricing-time
  personnel snapshot. Every other priced game is a PASS row: recorded,
  graded for accuracy/CLV diagnostics, never counted as a selection.
  Every game the lane captured with an entry snapshot is priced; every
  pick the rule emits counts.
- **Fireability invariant (freeze-blocking):** the freeze's unit tests
  must assert, at the pinned σ per market, `Φ(3.0/σ) ≥ 0.545` and
  `Φ(5.0/σ) ≥ 0.60`. If either assertion fails, there is no freeze. (This
  is the test whose absence let the retired construction ship a pick rule
  that could never fire.)

## 4. Population, validation split, and schedule

- **Population:** every NFL REG game with a lines-lane entry snapshot
  (T-1H write) and a closing snapshot (final write) in its game issue +
  registry. Coverage is whatever the lane actually captures; the slate
  coverage rate is reported at every checkpoint.
- **Validation split (the only data that can judge this construction):**
  all population games with kickoff **strictly after the freeze commit's
  timestamp** — in practice the remainder of the 2026 REG season from the
  freeze date. **2020–2025 are design data and 2026 games already played
  at freeze time are excluded forever** (they are neither design inputs —
  the design never fitted them — nor validation rows; no backfill, per
  standing law).
- **First eligible slate:** the first Sunday slate with ≥ 8 captured
  games whose entry snapshots all post strictly after the freeze
  timestamp **and** after the §7 landing check passes. The freeze record
  names the slate by date if known.
- **Validation window:** freeze → end of the 2026 REG season. If a market
  has < 40 graded picks at window end, that market's window extends
  through **2027 Week 6** (REG). The verdict review for a market happens
  **once**, at its window close or when a §6 kill fires, whichever first
  (anti-peeking: checkpoints report counts, CLV, ROI, coverage, and band
  calibration **without** verdict language; the rows graded at the review
  are the sample of record; no re-review at a later count without a new
  version's preregistration).

## 5. Pass criteria — per market, ALL required

1. **Sample:** ≥ 40 graded picks in the market inside its validation
   window (graded = result known, row admissible under §8).
2. **ROI:** ROI > 0 at actual captured DK entry prices (pushes excluded
   from the denominator, counted and shown).
3. **CLV:** mean CLV > 0 on same-line rows at actual captured DK lines,
   under the §8 close rule; **and** the §8 second test passes (adverse
   line moves do not significantly outnumber favorable ones, one-sided
   sign test α = 0.05, judged at α = 0.05/k under the multiple-testing
   policy); and the coverage label is not LOW_COVERAGE-only (§8 rule 4);
   and the INSUFFICIENT_CLOSE_DATA trip (§6.4) has not fired.
4. **Calibration (the retired constructions' Screen 3, moved forward):**
   across all priced games (picks + passes), realized cover of the
   model's preferred side by prespecified |d_entry| band —
   [0,1), [1,2), [2,3), [3,5), [5,∞) — satisfies **all** of:
   (a) one-sided Cochran–Armitage trend test p < 0.05 (increasing);
   (b) no band with n ≥ 30 overstates realized cover by > 7.5 pp against
   the band's mean stated p;
   (c) the top stated band's (p ≥ 0.58) realized cover ≥ 55% (if that
   band has n ≥ 30; if it has n < 30 the market cannot pass on this
   criterion and the window extension rule applies once).
5. **Accuracy sanity:** the construction's full-slate MAE per market ≤
   the closing line's MAE + 0.25 pts on identical priced games. (Design
   data puts the core ≈ +1.1/+0.7 behind the close; this criterion is
   the preregistration's way of saying the entry-time information state
   must close most of that gap or the construction is not what it
   claims. It is expected to be the hardest criterion after §5.4.)
6. **Both baselines beaten:**
   (a) *Existing model:* the construction's full-slate MAE ≤ Lane A's
   MAE on identical priced games, **and** the construction's pick ROI
   (§5.2) exceeds the ROI of Lane A's projections passed through the
   identical pick rule (§3), with Lane A's deviation given the same
   residual-agreement leg (the frozen §3 path applied to Lane A's sign).
   Lane A = repo-root `free_models.py` at the freeze commit, run by the
   evaluator adapter on identical point-in-time inputs, its projections
   recorded per game beside the construction's.
   (b) *Market baseline:* §5.2 + §5.3 + §5.5 jointly constitute beating
   the contemporaneous market baseline; the nflverse closing snapshot
   for the same games is reported alongside as a cross-check, labeled
   vs-close, never verified CLV.

Anything short of all six is **not verified** — the market keeps its
research label regardless of closeness. There is no partial credit.

## 6. Kill criteria — pre-registered, fail fast

Checked at every weekly checkpoint (after each slate's grading). A fired
kill stops new picks in that market immediately and moves that market to
its verdict review on the rows graded at the trip. Kills are per-market.

1. **Calibration kill.** At ≥ 25 graded picks: if the top stated band
   (p ≥ 0.58) has n ≥ 15 and realized cover below break-even at the
   prices taken (52.4% at −110; computed at actual prices) → killed.
2. **CLV kill.** At ≥ 30 graded picks: mean same-line CLV ≤ **−0.50
   pts** → killed.
3. **Accuracy kill.** At ≥ 40 priced games: construction MAE exceeds the
   close's MAE by **> 1.0 pt** in that market → killed, verdict FAILED.
   (Disclosed: the design-data gap is 1.11 pts for margin. This kill is
   expected to be live from the first checkpoint; that is its purpose.)
4. **Coverage kill.** At any checkpoint with ≥ 25 picks: true capture
   failures (§8 rule 3) exceed 20% of graded rows → verdict
   INSUFFICIENT_CLOSE_DATA; the clock does not advance on bad data.
5. **Integrity kill (fail closed, no threshold).** Any pick priced from a
   post-kickoff snapshot, a backfilled or edited close, a non-DK source,
   or a record altered after the fact → the family fails closed pending
   Isaac's review. One instance is enough.

## 7. Freeze checklist — exactly what gets pinned (Isaac's act)

1. This preregistration, finalized — sha256 in `SPEC_HASHES.txt` in a new
   directory `research/nfl_entry_form_v2_20261028/` (this directory's
   contents, finalized), following the Part 2 convention.
2. `DESIGN.md` at the reviewed head — sha256 pinned.
3. Construction code at an exact commit: EPA core, residual-agreement
   path, pick rule, probability map; module `__file__` proof in every
   run record; the §3 fireability unit tests passing on the exact head.
4. **Constants file** (sha256-pinned) containing exactly: shrinkage
   priors (250 plays; form 150 plays; carries 0.30 / QB 0.50; QB prior
   200 attempts); eligibility (3 prior REG games); the per-market OLS
   coefficients (core and residual paths) as fitted on 2020–2025 design
   data; fitted HFA; per-market σ_fit with the 12.5 floor stated;
   thresholds (|d| ≥ 3.0; p ≥ 0.545; price ≥ −165). Any number not in
   this file does not exist in the construction.
5. The design screen report (`SCREEN_RESULTS.md`) filed with the freeze,
   labeled **DESIGN DATA — ZERO VALIDATION CREDIT** on its face,
   including its negative results.
6. **Evaluator pin:** the shared forward evaluator at an exact commit +
   this family's adapter at an exact commit, with a named fail-closed
   refusal (e.g. `EF_V2_FREEZE_NOT_AUTHORIZED`) if counted evaluation is
   attempted against an unfrozen or mis-pinned construction; no
   caller-controlled bypass.
7. **Data contracts:** (a) nflverse weekly team/player files + games
   file — source URLs and per-run retrieval hashes (pins per `PINS.json`;
   the games file pin is inherited from PR #2831 once landed);
   (b) the lane snapshot contract — the registry/issue fields constituting
   entry and close snapshots, their Captured timestamps, and the
   150-second countable-evidence admission standard per row (distinct
   from the 30-minute card pricing window, per standing law);
   (c) the personnel-state source at pricing time and the
   snapshot-into-record rule; (d) the §8 close rule by reference to the
   pinned evaluator.
8. **First eligible slate** per §4, named by date or by rule, plus the
   landing check (full path capture → price → record → grade proven on a
   non-counted slate) scheduled and verified **before** that slate.
9. **Governance registration:** research-only registration
   (`REGISTERED_RESEARCH_ONLY` — registration is not an engine and not an
   admission), `verified_play = false`, PAPER/0u.

## 8. Close rule — the Oct 22 v1.1 amendment, carried in unchanged

Applies verbatim (implemented in the shared forward evaluator with the
five frozen reason codes `NO_CLOSE_ROW`, `LINE_MOVED`,
`CLOSE_SINGLE_SIDED`, `CLOSE_NOT_PREKICKOFF`, `CLOSE_STALE`):

1. A row whose closing line differs from its entry line is `LINE_MOVED`:
   it stays in win/loss, leaves the primary CLV average, and enters the
   moved bucket with move direction recorded (favorable/adverse, from
   the pick's perspective). No repricing, no backfilled close — ever.
2. The moved bucket is a second verdict test (§5.3): primary CLV must
   pass **and** adverse moves must not significantly outnumber favorable
   ones (one-sided sign test, §5.3).
3. The 20% INSUFFICIENT_CLOSE_DATA trip counts only true capture
   failures (`NO_CLOSE_ROW`, `CLOSE_SINGLE_SIDED`, `CLOSE_STALE`,
   `CLOSE_NOT_PREKICKOFF`); `LINE_MOVED` never counts toward it.
4. If moved rows exceed 50% of a market's graded picks, that market's
   CLV verdict is labeled LOW_COVERAGE and cannot open PLAY by itself.

## 9. Non-interference and amendment discipline

This preregistration touches nothing frozen: NFL props Part 2/2B, ATD
v1.1, the passing-yards v2 screen, and every other family's prereg,
evaluator, and clock are untouched; the shared forward evaluator is used
read-only by pin. Amendments after freeze are new versions with their own
preregistrations, scored forward only, exactly as the program's v1.1
amendment discipline has always required. Post-verdict model adjustments
(the owner's adjust-from-logged-results loop) likewise happen only as new
versions — never as silent edits to a frozen construction.

---

## 10. Pins (freeze package; sha256 hashed on main `a61fe0029`)

Per §7.1–§7.3 and §7.6. This document's own sha256 cannot be stated
inside it; it is recorded in `SPEC_HASHES.txt` in this directory and
in `FREEZE_ACT_CHECKLIST.md`, and the freeze act re-verifies it on
the act's head before recording it as the config's `prereg_sha256`.

| Artifact | sha256 |
|---|---|
| Construction `sportsedge/nfl_entry_form_v2.py` | `5febc4e74df32e1ad2bf4e2e8b74f65c677e7564ef0d02071d6e90c2f99627b9` |
| Constants file `sportsedge/nfl_entry_form_v2_constants.py` | `cee85fcedb848e43eded5b64477c6d9d0a197d45e22e7de80286f2207fa8d603` |
| Evaluator adapter `sportsedge/nfl_entry_form_v2_evaluator.py` | `d547a436eb93d739beae3c06e1397fa0855cc6fa23dfb88dbaf96e30741b36f0` |
| Fitted constants record `research/nfl_entry_form_v2_20261028/fitted_constants.json` | `a0ed28241648a98c7b6b7ee9e7166b04964a6914b5abb65765c06a230ee02820` |
| `DESIGN.md` (this directory) | `b75e317060a59826356a28b41434aaeac6d997e0917d067e2939bc48ab8d1f2a` |
| `SCREEN_RESULTS.md` (this directory; DESIGN DATA — ZERO VALIDATION CREDIT, §7.5) | `ac85758ee3afcf063c5a561cd9a8562ee3cceeda48ada78cf3e4d251927519b6` |
| Superseded draft `PREREG_DRAFT.md` (this directory, retained) | `8fc90394d47cb7f30656f282e8bc27dee90acb46d72115b066374ad6ead40616` |
| Lane A `artifacts/free_models.py` (§5.6a baseline; byte-identical to the pins recorded in the NFL team-totals freeze record) | `a8abf4606acafd2405ec037ea3bf69f1a6a5168baa4750631cc0fbebcece1fa3` |
| Lane A root shim `free_models.py` | `9160bbd3fd02147875942a709d2793e001281886a0969758acbcfdadf4356f67` |
| Family config (draft) | `CONFIG_DRAFT.json` in this directory; pin in `SPEC_HASHES.txt`. Installs as `sportsedge/forward_validation/configs/nfl_entry_form_v2.json` only at the freeze act — see §14 and the checklist's registry gate. |
| Data contracts (§7.7) | `PINS.json` in this directory: nflverse games file sha256 `82b05d7096b3f59acd127da8762b1e2260f4af70b49e5548ce4cd3ade92a49a5` (inherited from PR #2831) + per-season weekly team/player parquets, each sha256-pinned there. Lane snapshot contract, personnel-state source, and the §8 close rule are as §7.7/§8 state; the adapter pin above is the close rule's implementation of record. |

The config's `model_version` is the pin string
`nfl_entry_form_v2@sha256:5febc4e74df32e1ad2bf4e2e8b74f65c677e7564ef0d02071d6e90c2f99627b9`
— the construction module's sha256. Any change to that file breaks
the pin until it is re-struck under a new version by a governed act.

## 11. Freeze-fit values (recorded from the §7 build; §3/§7.4)

The fit the freeze pins is the build's fit: **one pooled OLS fit on
all 1,327 eligible 2020–2025 design rows, fitted once** (READING 1,
§12; fit program `fit_constants.py`, record `fitted_constants.json`,
both in this directory). No refit during validation, for any reason
(§3).

- **Core mapping — SPREAD:** intercept (fitted HFA) **1.8157**
  (1.815740331071083); EPA margin 0.25732; form divergence −0.03423.
- **Core mapping — TOTAL:** intercept 45.7744; EPA total 0.11994;
  form divergence 0.05602.
- **Residual-agreement path — SPREAD:** intercept 0.32100; form
  divergence −0.00200; QB EPA delta (home) −0.01513; QB EPA delta
  (away) −0.00726; rest 0.04669.
- **Residual-agreement path — TOTAL:** intercept 1.06456; form
  divergence 0.04772; pace deviation −0.00045; wind 0.34157;
  cold 1.82716.
- **σ_fit (per market, floor 12.5 — not binding):** SPREAD
  **14.0347** (14.034734387117979); TOTAL **13.7368**
  (13.736836529512287). These supersede the design-stage walk-forward
  values (14.40 / 13.95) exactly as §3 prescribes: the freeze fit
  governs.
- **Fireability at the pinned σ (§3, freeze-blocking, unit-tested on
  the pinned constants in `tests/test_nfl_entry_form_v2.py`):**
  Φ(3.0/σ) = 0.5846 (SPREAD) / 0.5864 (TOTAL) ≥ 0.545 ✓;
  Φ(5.0/σ) = 0.6392 / 0.6421 ≥ 0.60 ✓.
- **Structural constants (§7.4, as pinned in the constants file):**
  shrinkage priors 250 plays (season EPA) / 150 plays (form);
  carries 0.30 (team) / 0.50 (QB); QB prior 200 attempts; eligibility
  ≥ 3 prior REG games, both teams; thresholds |d| ≥ 3.0, p ≥ 0.545,
  picked-side price ≥ −165; σ floor 12.5.

The freeze act verifies the constants file on its head hashes to the
§10 pin. A re-fit producing different bytes is a different constants
file: it requires a package amendment and re-review before the act,
never a silent substitution at the act.

## 12. Readings — FREEZE PACKAGE PROPOSALS

The build (`BUILD_RECORD.md`, PR #2869) took four readings where the
draft's wording needed one. Each is recorded here as a **READING —
FREEZE PACKAGE PROPOSAL, open to Rocky/owner correction before the
freeze act**. The freeze act pins the readings as corrected or as
confirmed; until then §§1–9 above stand as written and no reading
changes any term.

- **READING 1 — fit shape.** §7.4 governs: the per-market mappings
  (core and residual paths) and σ are **one pooled fit on 2020–2025
  design data, fitted once**. DESIGN.md §4.1's parenthetical
  "(2020–2025 walk-forward residuals)" is read as describing the
  design screens' evidence, not the freeze fit. (This is why the
  freeze σ in §11 differs from the screens' walk-forward means —
  14.0347/13.7368 vs 14.40/13.95; both clear the floor and the §3
  fireability test.)
- **READING 2 — §6.2 CLV-kill units.** "Mean same-line CLV ≤ −0.50
  pts" is read in the shared forward evaluator's CLV units (no-vig
  probability): **−0.50 pts = −0.0050 probability points**. A
  line-points reading is incoherent on same-line rows — their line
  CLV is identically 0, which would make §5.3's mean-CLV > 0
  unsatisfiable — so the probability reading is the only consistent
  one. The adapter implements it in these units.
- **READING 3 — §8 moved-row direction.** The v1.1 convention of
  record applies (NBA team-totals evaluator §6c): **favorable = the
  close moved toward the picked side**, generalized to spreads as
  HOME up / AWAY down in home-margin units. The adapter implements
  direction in exactly this convention.
- **READING 4 — two constants sourced from the reference
  implementation.** The QB-delta attempt scale (**36**) and the
  pace-deviation center (**124.0**) are not printed in DESIGN.md;
  both are taken verbatim from `design_screen.py`, the reference
  implementation DESIGN §4.2's feature set is defined by, and are
  cited as such in the pinned constants file
  (`QB_DELTA_ATTEMPT_SCALE`, `PACE_LEAGUE_REFERENCE`).

## 13. Annotation — the DESIGN §4.2 agreement evidence was measured at closes

Build finding (PR #2869, `BUILD_RECORD.md`, answering the design
review's open question, PR #2849 comment 6463091073): the
residual-agreement evidence behind DESIGN.md §4.2 — lone-signal
(disagreement) rows covering 47.3% at −7.9% ROI — was measured at
**closes**. `SCREEN_RESULTS.md`'s method grades every screen against
the nflverse **closing** snapshot ("vs-close, never verified CLV"),
and its Screen 3 disagreement row (n = 315) is computed with
deviations from that closing snapshot, with the residual path fitted
on close residuals. **No entry-line measurement exists in the
record**: no admitted historical source holds T-1H entry lines
(gap G7). The §2 claim is therefore untested at entry lines by
design evidence and is judged only forward, on captured entry
snapshots, under §4. Nothing in this annotation changes the claim,
the path, or any criterion; it fixes the evidence basis on the face
of the preregistration so the freeze does not inherit an ambiguity.

## 14. First counted slate, evaluator state, and the freeze act

- **First counted slate: the first NFL slate priced by the pinned
  construction after a freeze act is recorded (no backfill).**
  Operatively per §4: the validation split is every population game
  with kickoff strictly after the freeze commit's timestamp; the
  first eligible slate is the first Sunday slate with ≥ 8 captured
  games whose entry snapshots all post strictly after the freeze
  timestamp and after the §7 landing check passes. The build's
  landing check (2025 Week 10, NON_COUNTED, on file in this
  directory) proves the capture → price → record → grade path; the
  freeze act's checklist re-verifies the live pricing path on a
  non-counted slate before the first eligible slate. 2026 games
  played before the freeze are excluded forever (§4).
- **Evaluator state until the act:** the pinned adapter raises
  `EF_V2_FREEZE_NOT_AUTHORIZED` at every counted entry point
  (`count_rows`, `score_counted`, `verdict`); diagnostics run
  NON_COUNTED only. There is no caller-controlled bypass, and none
  may be added. The freeze act records the evaluator pin (the shared
  forward evaluator at an exact commit + this adapter at the §10
  pin) in the family's freeze record; counted evaluation is
  authorized only under that recorded pin and a FROZEN config.
- **The act:** `FREEZE_ACT_CHECKLIST.md` in this directory mirrors
  the NFL team-totals freeze sequence (freeze-prep PR #2858 →
  freeze-act PR #2860): review closes on the act's exact head before
  its merge records the freeze; the config flip DRAFT → FROZEN is
  part of the act, not of this package; the multiple-testing k is
  recomputed at the act (this package computes k = 12 — see the
  checklist) and again at any verdict, the larger governing.
