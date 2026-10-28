# FREEZE RECORD — NFL Team Totals Forward Test V1

**Status: THE FREEZE IS RECORDED AT MERGE OF THE FREEZE-ACT PULL
REQUEST THAT CARRIES THIS RECORD.** The freeze-act PR stacks on the
freeze-prep package (PR #2858, branch
`rocky/nfl-team-total-freeze-prep-20261028`, base head `3b60cc2f9`)
and targets main as a draft for independent exact-head review.
**Before that merge, nothing in this package is in force: the config
flip committed in the freeze-act PR is not counting, no clock has
started, and no slate counts. The freeze takes effect only at the
merge — never at commit, push, or review.** Independent review
(Rocky) closes on the freeze act's exact head BEFORE the merge
records the freeze (the sequencing the NBA props V2 quarantine
taught: review first, freeze second, no exceptions).

- Freeze timestamp: **recorded at merge of this PR** (the merge
  commit's timestamp on main is the freeze instant; no timestamp is
  asserted in advance).
- Document: `research/nfl_team_totals_forward_20261028/PREREG_NFL_TEAM_TOTALS_FORWARD_V1.md`
- This package's frozen preregistration sha256:
  `83f25f0e92c3ea39c8b18e194ce5743ceff6b595dc7dcb342175a57e46743581`
- The superseded draft preregistration
  (`PREREG_NFL_TEAM_TOTALS_FORWARD_V1_DRAFT.md`, sha256
  `c2f7f0934b52a8a3c6955692abe19d0312297ffd69701c2819c105755a24e224`)
  is retained in this package as the historical draft; the frozen
  text differs from it only in status, provenance, pins, the §2
  record list's Lane A field, the §9 seed instantiation, and the
  §12 checklist state — no statistical term, threshold, or rule
  changed (verified by diff at the freeze act).
- Design origin: NFL activation pack, draft PR #2852
  (`research/nfl_activation_20261027/` — DESIGN + prereg draft + screen).
- Authority: owner ruling under the owner's Oct 27, 2026 decision
  delegation, executed through this governed recording.

## Pins (sha256, recomputed at the freeze act on the freeze base head)

| Artifact | sha256 |
|---|---|
| Engine `sportsedge/nfl_team_total_dist.py` | `50c5d9ff068b3bf629a725d5713a956d3149565c2f29c59ac8af3fc6461dcc27` |
| Runner `sportsedge/nfl_team_total_runner.py` | `076da740f5ac0517bbe2f52b28decf77d9923226c51a8228ff5e57b4b14f323e` |
| Framework config `sportsedge/forward_validation/configs/nfl_team_total.json` | `4c5d7afbfe97d0c5f48644b7fe36c2f7666fba6caf10421f16e3a516485aa3d7` |
| Preregistration (frozen, this package) | `83f25f0e92c3ea39c8b18e194ce5743ceff6b595dc7dcb342175a57e46743581` |
| Engine tests `tests/test_nfl_team_total_dist.py` | `6a23308516832507cccce36cc056e75fc9ebaca66af313e14d723e189fb4c91a` |
| Runner tests `tests/test_nfl_team_total_runner.py` | `e3dd97d83c381d513bbec25e5f5ebf506207f97f5818efedb954b91496aed922` |
| Lane A `artifacts/free_models.py` | `a8abf4606acafd2405ec037ea3bf69f1a6a5168baa4750631cc0fbebcece1fa3` |
| Lane A root shim `free_models.py` | `9160bbd3fd02147875942a709d2793e001281886a0969758acbcfdadf4356f67` |
| Reproduction harness `reproduce_screen_with_engine.py` | `93022b5d526236d95261b75555d6a056330c4bdf358cbf53435810ae83d203ee` |
| Full pin list | `SPEC_HASHES.txt` in this package |

The config's `model_version` is the pin string
`nfl_team_total_dist_v1@sha256:50c5d9ff068b3bf629a725d5713a956d3149565c2f29c59ac8af3fc6461dcc27`
— **unchanged from the freeze-prep package and verified equal to the
engine file's sha256 at the freeze act**: any change to the engine
file breaks the pin (and the binding tests in
`tests/test_nfl_team_total_dist.py`) until the pin is re-struck under
a new version.

## The runner (preregistration §11–§12 hard gate)

The freeze-prep package carried no forward runner. The freeze act
builds it — a freeze of an un-runnable clock would be a hollow act.

`sportsedge/nfl_team_total_runner.py` (`NFL_TEAM_TOTAL_RUNNER_V1`,
pin above) prices a slate's paired DK team-total ENTRY captures with
the pinned engine and writes create-only run records carrying, per
row: the engine mean μ_T and the full NB distribution (pmf grid),
B1/B2 reference means, the entry line and both prices with their
capture timestamps, model probabilities / fair odds / EV for both
sides, the §5 pick classification, entry no-vig probabilities,
**Lane A's emitted mean for the same team-game** (§6b), and the
sha256 pins of the engine, runner, config, preregistration, and the
slate's history snapshot. At settlement, `evaluate_close` attaches
the valid close under §7 (last paired capture before kickoff, no
more than 60:00 before it) with exactly one disposition per row, and
the final team points / VOID / RESULT_UNAVAILABLE / push state (§3).

Runner discipline, declared as part of its pin (§7–§8): construction
refuses the whole run on `MODEL_VERSION_MISMATCH` (config pin ≠
engine file) or `HISTORY_SNAPSHOT_INVALID` (a non-final or
non-regular-season game in the history snapshot); per-row refusals
(one code per row, never aborting the slate, never zero-filled) are
`ENTRY_CAPTURE_MISSING`, `ENTRY_SINGLE_SIDED`, `ENTRY_NOT_PRE_EVENT`,
`ENTRY_PAIR_SPAN_EXCEEDED` (>120 s between ENTRY side quotes),
`QUOTE_STALE_180S` (priced more than 180 s after the earliest ENTRY
side quote), `PRICE_INVALID`, `LINE_INVALID`,
`LANE_A_EMISSION_MISSING`, `DUPLICATE_ROW`. Close dispositions:
`READABLE`, `LINE_MOVED` (with v1.1 favorable/adverse direction),
`NO_CLOSE_ROW`, `CLOSE_SINGLE_SIDED`, `CLOSE_NOT_PREKICKOFF`,
`CLOSE_STALE`, `PAIR_SPAN_EXCEEDED` (>150 s between CLOSE side
quotes). The record writer is create-only: it refuses to overwrite
an existing slate record file.

**Evaluator pin: PENDING.** No §6 metric may be computed until the
family evaluator is pinned by amendment; the preregistration's §4
no-interim-looks rule binds in the meantime. The run records carry
every input a pinned evaluator needs, so pinning it later rewrites
nothing.

## Construction identity

`NFL_TEAM_TOTAL_DIST_V1`: point-in-time shrunk offensive × defensive
team means over a negative-binomial law — same-season prior games
supplemented by prior-season games to 8, league pool mean G, K = 3
shrinkage, μ_T = off_T · def_O / G, NB with variance (c·μ_T)², c =
0.46438741207903494 from the 2018–2019 training seasons only. **Zero
market input** — no spread, total, or line enters any feature or the
probability path. Explicitly **not** a resurrection of the retired
NFL_ANCHORED_RATINGS_V1 (market-anchored, FAILED_SCREEN, stays
retired): this construction's only contact with the market is as the
baseline its forward test must beat.

## Screen evidence (design screen, reproduced with the built engine)

Design screen (activation pack, criteria fixed before the run):
**PASS** vs the point-in-time naive baselines — pooled MAE 7.749 vs
B1 7.831 / B2 7.924; pooled CRPS 5.528 vs 5.590 / 5.625; n = 3,230
team-games, 2020–2025; PIT mean 0.537; 91.0% inside the central 90%
band.

Reproduction with the built engine (this package,
`SCREEN_REPRODUCTION.md` + `screen_reproduction_results.json`): the
nflverse pull was byte-identical to the design pull (sha256
`1b4ca0c7…`), and **every number reproduced with delta exactly 0.0**,
including the training constant c. Screen verdict under the
pre-committed criteria: **PASS**, as designed. No tuning was performed
or needed; had the built engine not reproduced the screen, this
package would have stopped and reported instead.

### The disclosure that travels with the pass (verbatim from the design)

**Disclosure, in the open (the NBA team-totals §0 pattern):** the
candidate beats the naive baselines it was screened against — narrowly
(≈0.08 MAE pooled) — and **loses clearly to the market's implied split**
(7.749 vs 7.250). The forward test's governing leg is accuracy against
the DraftKings closing team-total line, and on this design evidence
that leg is the expected-risk leg: the DK team-total line is not a
naive (total ∓ spread)/2 split of a stale total — it is a traded line
informed by the closing spread and total, which are themselves sharp.
The construction advances to ARMED-pending-freeze because the screen it
was given asked about the naive baselines and it passed, and because
the forward test — not this screen — is where the market question is
answered, with the moved-row and CLV legs measuring something MAE
against a snapshot cannot. Anyone reading this pass as market evidence
is misreading it.

## Forward-test terms (from the frozen preregistration, copied terms)

- **Governing leg §6a — accuracy vs close:** paired per-row ΔMAE of
  the engine mean vs the DraftKings closing team-total line; the §9
  interval's upper bound must lie below 0.
- **§6b — accuracy vs the existing model (Lane A):** the engine's mean
  must beat Lane A's emitted mean for the same team-game (Lane A
  hash-pinned above; its emitted means recorded in the run record),
  same interval rule. This is the Oct 27, 2026 validation law's
  second baseline.
- **§6c — CLV:** mean CLV on PICKED rows > 0 (interval lower bound
  above 0) AND picked mean CLV > passed mean CLV, on rows whose valid
  close is at the entry line.
- **§6d — hit rate vs the market** on PICKED rows at the entry line.
- **Moved-row rules (NFL props v1.1):** checked first, in order —
  (1) adverse-vs-favorable moved PICKED rows significant at α/k in the
  adverse direction (one-sided exact sign test) → DOES_NOT_BEAT_MARKET
  regardless of §6a–§6d; (2) else moved PICKED rows > 50% →
  INSUFFICIENT_CLOSE_DATA. Zero moved picked rows: the sign test is
  not run and rule 1 does not apply. >20% of rows without a valid
  close → INSUFFICIENT_CLOSE_DATA.
- **Gates (minimums):** ≥4 full slates AND ≥150 engine-priced rows
  with valid close pairing AND ≥40 distinct games AND ≥50 picked
  rows. **The verdict review happens once**, at the first slate close
  where all gates are met; no interim looks at the primary metrics.
- **Pick rule (fixed):** gap = μ_T − entry_line; PICKED OVER if
  gap ≥ +2.0, PICKED UNDER if gap ≤ −2.0, else PASSED.
- **Intervals:** game-cluster bootstrap, 10,000 resamples, two-sided
  at level 1 − α/k, α = 0.05. **Bootstrap seed: 20261028 (binding).**
- A BEATS_MARKET verdict is this family's pass under the Oct 27, 2026
  validation law; it changes no registration or eligibility by itself,
  and no verdict under this test creates a PLAY.

## First counted slate (instantiated)

**The first NFL slate priced by the pinned runner after this
freeze-act PR merges to main.** Rows priced before the merge never
count — no backfill: pre-merge rows are historical record, never
prospective entries, and no §6 primary metric is computed on any
forward row before the first counted slate.

## α = 0.05/k — k counted as of the freeze

Per preregistration §9, k = the number of families validated or under
active forward test in the program whose windows overlap this test's
window, counting this test from its freeze date; the list is recorded
at freeze and again at review, and the larger k is used (the
Oct 22, 2026 policy: k is recomputed at verdict; the freeze-time
table below binds until then). Counted conservatively, in the NBA
team-totals freeze record's manner — a clock that is frozen, locked,
or ruled to run and may count rows during this window is included
even if its own counting has not started:

| # | Clock | State as of the freeze |
|---|---|---|
| 1 | NFL_PROPS_PART2_FORWARD_V1 | frozen, running |
| 2 | NFL_PROPS_PART2B_FORWARD_V1 | frozen, running |
| 3 | NFL_PROPS_V1_1_MOVED_LINE_AMENDMENT | counted separately, conservatively (as in the NBA team-totals freeze record) |
| 4 | NBA_PROPS_FORWARD_V1 | frozen clock (per the NBA team-totals freeze record) |
| 5 | NFL_TOTALS_LEVEL_V2_FORWARD | forward leg scores Jan 13, 2027 — window overlaps |
| 6 | MLB_PITCHER_PROP_PROMOTION_V2 (pitcher-K ridge) | forward clock running |
| 7 | NFL_ANYTIME_TD_FORWARD_V1 (v1.1 terms) | frozen; counting-armed, accrual from Nov 1, 2026 slates |
| 8 | NFL_PASSYDS_V2_FORWARD_SCREEN | forward screen; population opens Oct 29, 2026 |
| 9 | NBA_TEAM_TOTALS_FORWARD_V1 | frozen Oct 22–23, 2026; armed, not yet counting (receipt act + eligibility pending) |
| 10 | NHL home-ice v2 (Stage A accuracy verdict) | locked forward test; verdict lands Nov 30, 2026 — window overlaps |
| 11 | NFL_TEAM_TOTAL_DIST_V1 forward test | this test, from its freeze (the merge of the freeze-act PR) |

**k = 11 → α/k = 0.05/11 ≈ 0.004545; intervals two-sided at
1 − α/k ≈ 99.545%.** Excluded, with reasons: NBA_PROPS_V2 — its
recorded freeze was quarantined by owner ruling (Oct 27, 2026: the
freeze does not establish a valid clock start); it has no active
clock. All DRAFT families — not frozen, no clock. **k is recomputed
at the verdict review per the Oct 22, 2026 policy; if the freeze and
review counts differ, the larger governs.**

## Adaptation log (vs the freeze-prep package #2858 and its drafts)

- Config: `status` DRAFT → FROZEN (string per the framework's frozen
  convention, naming the preregistration and this record);
  `prereg_draft` replaced by `prereg` + `prereg_sha256` (the frozen
  preregistration's pin). `model_version` and every gate/threshold
  value are byte-identical to the freeze-prep config.
- Preregistration: finalized as
  `PREREG_NFL_TEAM_TOTALS_FORWARD_V1.md` from the draft — diff-verified:
  status/provenance/pins, the §2 Lane A record field (completing
  §6b), the §9 seed instantiation (20261028, as proposed in the draft
  record), and the §12 checklist state only. No statistical term,
  threshold, or rule changed.
- Runner: BUILT by the freeze act (the freeze-prep package had none)
  with its test suite; its pin, constants, and code set are recorded
  above.
- Lane A pins: added at the freeze act (the draft record's §12
  checklist carried this as an open item; the runner + its tests
  close it — see the checklist below).
- k: the draft record's provisional table (k = 10) gains one row —
  the NHL home-ice v2 Stage A locked forward test, whose Nov 30, 2026
  verdict window overlaps this test's window — under the same
  conservative counting convention the draft record itself states.
  k = 11 binds at freeze; recomputation at review may only raise it
  in effect (the larger governs).
- `tests/test_nfl_team_total_dist.py`: the config binding test's
  status assertion updated DRAFT → FROZEN, and extended to assert the
  config's `prereg_sha256` equals the frozen preregistration's file
  hash. No other assertion changed.
- The design screen's period-lines construction (NFL_PERIOD_SHARE_V1)
  recorded FAILED_SCREEN in the activation pack and is **not** part of
  this package; nothing here resurrects or retunes it.

## Freeze checklist status (preregistration §12)

- [x] Engine build of `NFL_TEAM_TOTAL_DIST_V1` committed with the
      hash-pin discipline (freeze-prep package #2858).
- [x] Independently reviewed — the freeze-prep package's exact head
      CLEARED by a checker who did not build it; **this freeze act's
      own exact head is independently reviewed before its merge
      records the freeze** (the merge is the recording act; nothing
      counts before it).
- [x] Lane A's emitted-means recording verified in the run record
      (§6b depends on it) — the pinned runner records Lane A's
      emitted mean on every priced row, and
      `tests/test_nfl_team_total_runner.py` demonstrates by direct
      comparison that the recorded mean equals Lane A's own
      `calculate` emission for the same team-game.
- [x] Bootstrap seed and the §9 k list recorded at the freeze act
      (seed 20261028, binding; k = 11 table above).
- [x] This document frozen by owner ruling under the Oct 27, 2026
      decision delegation; the first counted slate is named above as
      **the first NFL slate priced by the pinned runner after the
      freeze-act merge**. No primary metrics (§6) are computed on
      forward rows before then.

*Freeze record finalized at the freeze act. The freeze is recorded
at the merge of the freeze-act PR; before that merge, nothing here
is in force.*
