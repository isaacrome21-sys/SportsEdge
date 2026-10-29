# PREREGISTRATION (REVISION DRAFT) — NFL quarter / first-half lines: forward test vs captured DraftKings prices

**Status: DRAFT — NOT FROZEN — NOT ADOPTED.** This revision names a
construction for the family's forward test. It freezes nothing,
adopts nothing, and counts nothing: **counted rows under this family
are zero**, and they remain zero until a separate prospective owner
freeze act — with independent review closed on the exact head
carrying the freeze — records the freeze and names the first counted
slate. Until that act, every counted entry point for this family
refuses fail-closed (§11). **Freezing is the owner's act. No game,
row, or slate counts toward this test before its freeze.** Rows
priced before a freeze are historical record, never prospective
entries. No verdict issued under this test creates a PLAY. PAPER /
0u throughout.

This document is the revision contemplated by §8 of the design
(`research/successor_designs_20261028/DESIGN_NFL_PERIOD_DRIVE_STATE_V2.md`)
of the draft it revises
(`research/nfl_activation_20261027/PREREG_NFL_PERIOD_LINES_FORWARD_V1_DRAFT.md`,
sha256 `e992296160d73d61cd0c15faf904a02d90f61af0f87da34d615de04988a17928`).
Per that design's §8, the revision's only substantive act is the §2
binding: naming the construction, its `model_version`, and its
sha256 pins, and recording its design-screen result. The forward
terms themselves — markets, gates, pick rule, §7 legs, close rules,
α/k accounting, the one-review rule — are the V1 draft's terms,
carried here verbatim in substance so the candidate frozen text
stands in one document; where the V1 draft's text and the frozen
precedents diverge in a way a reader could trip on, the divergence
is resolved in favor of the V1 draft (this family's own fixed
terms) and flagged in §14. Structural precedents followed: the
frozen NFL team-totals preregistration
(`research/nfl_team_totals_forward_20261028/PREREG_NFL_TEAM_TOTALS_FORWARD_V1.md`,
PRs #2858/#2860) and the NFL props v1.1 close-rule amendment to the
frozen Part 2 test (owner ruling, Oct 22, 2026).

Framework config:
`sportsedge/forward_validation/configs/nfl_period_lines.json`
(sport NFL, family PERIOD_LINES; sha256 at this revision
`7d677a841f3edb82a3809bdc97a7866779b89643f0c6eae41eaee5b16803f045`).
At the freeze act — and not before — this document and that config
freeze together: the config's `model_version` flips from the
`UNPINNED` sentinel to the §2 pin string and its status flips to
FROZEN, in the freeze act's own commit set (the NFL team-totals
precedent). This revision does not touch the config (§14, FLAG 4).

Verdicts issue **per market, never pooled** (the Part 2 rule) —
Q1 total and Q3 spread are different markets with different
verdicts.

## 0. Up-front risks (read before anything else)

1. **The screen margins are thin.** The construction passed its
   design screen with pooled MAE(M) **4.40068** vs B0 **4.42281** —
   a margin of ≈0.5% over the league-share baseline — and the
   bucket leg passed **exactly at its 4-of-6 minimum** (Q3, Q4, 1H,
   2H; Q1 and Q2 lost to B0). This is an entry ticket, not momentum:
   the forward test's §7b accuracy leg against B0 for quarter
   markets is, on the screen's own numbers, a leg this construction
   can plausibly fail, and a failure is `DOES_NOT_BEAT_MARKET`,
   recorded as such.
2. **The simulator's level runs low.** The screen's base-rate
   diagnostic (disclosed in the screen report, not patched): the
   simulation chain produces ≈1.7 fewer points per team-game than
   both the training record and the frozen sibling's means (2024
   and 2025 fits failed the diagnostic's points band; plays, TD
   share, and punt share passed). No level correction was applied —
   the design fixes no correction channel — so the construction
   enters this test exactly as screened, level shortfall included.
   Period *means* feed the §6 pick rule's gaps; a level-biased mean
   shows up there first, and the record should expect it to.
3. **No market leg exists yet.** The screen's baselines are model
   baselines (B0/B1), not prices: period lines were never captured
   historically. Every market question in this test is open, and
   the capture precondition that would let it be asked (§4) is
   still unlanded.

## 1. Markets in scope

Quarter markets, each two-sided at DK's main line: `TOTAL_1Q`,
`SPREAD_1Q`, `ML_1Q`, `TEAM_TOTAL_1Q`, and identically for 2Q, 3Q,
4Q; first-half markets: `TOTAL_1H`, `SPREAD_1H`, `ML_1H`,
`TEAM_TOTAL_1H` — the twenty markets carried by the framework
config. Second-half markets are **out of scope** (in-play prices;
assigned to the live family — see the design doc). Settlement is
regulation period scoring only: a quarter market settles on that
quarter's points; 1H on Q1+Q2; overtime never enters any market in
this family. Line storage follows the framework convention (`line`
on the realized-value scale for the over side; a home quarter
spread stored on the home-margin scale with over_side HOME).

## 2. The construction bound (the revision's substantive act)

**Construction: `NFL_PERIOD_DRIVE_STATE_V2`** — the drive-level,
game-state-conditioned period construction of the design
(drive-by-drive simulation; state = score differential × time
remaining in the design's §3.2 fixed buckets modulating pace, play
selection, and scoring environment as league-level point-in-time
functions; team identity only through §3.3 point-in-time rates;
joint distribution over the four quarters' points for both teams
per game; R = 10,000 replications; play-by-play drive generation
per build reading RD-1, with readings RD-1…RD-11 recorded in the
pinned implementation's header before any screen statistic was
computed).

**`model_version` pin string** (the value the framework config
carries from the freeze act forward):
`nfl_period_drive_state_v2@sha256:16593a8779986f653705c481eaf0e079387933975123e386f8efd7e865b4658c`

**sha256 pins** (recomputed on main `be8d19a1e`, the base of this
revision; full set in this package's `SPEC_HASHES.txt`):

| Artifact | sha256 |
|---|---|
| Design — `research/successor_designs_20261028/DESIGN_NFL_PERIOD_DRIVE_STATE_V2.md` | `50b5f556ebcb6c7f951afdc8138595f4902a8a93bced8b22b85c5f8a0c257f1e` |
| Engine (construction implementation of record) — `research/nfl_period_drive_state_screen_20261028/screen_nfl_period_drive_state_v2.py` | `16593a8779986f653705c481eaf0e079387933975123e386f8efd7e865b4658c` |
| Screen results — `research/nfl_period_drive_state_screen_20261028/screen_results_v2.json` | `7089e33b7a6f6ba28d7776445515ebc7a38474f9ba7449c480897909f3d65cb8` |
| Screen report — `research/nfl_period_drive_state_screen_20261028/SCREEN_REPORT.md` | `b584f1cd7c42eec43e5d494dcbfdf1af36868cf170bf6aa04e5e5a12eca8aa0a` |
| Screen tests — `tests/test_nfl_period_drive_state_v2.py` | `885e906cf7a58cde8f0b87ce5d3a133f150d1e2c7b3a9cb8ed5c7d48a42fd74f` |
| §7b 1H baseline (Lane A surface) — `sportsedge/team_half_pricing.py` | `3d76cf730111d75c415a682e3f733b1374e19745f61b49b83dfb68e06f430308` |
| §7b B0 level source (frozen sibling engine) — `sportsedge/nfl_team_total_dist.py` | `50c5d9ff068b3bf629a725d5713a956d3149565c2f29c59ac8af3fc6461dcc27` |

The engine pin covers the constants as built: the §3.2 state
buckets and state functions, the §3.3 rate construction, and the
simulation discipline are all inside the pinned implementation
(there is no separate constants file). The simulation master seed
of record is the screen's seed A, **20261028** (seed B, 20261029,
was the pre-declared second execution; per-game streams derive
from (master seed, game index) — forward pricing uses the same
derivation, with the slate's game index order committed in the run
record). The sibling engine pin above is byte-identical to the
frozen NFL team-totals pin of record; the sibling is a read-only
input here and is not modified by anything in this package.

The construction takes **no market input**. It produces, per
team-game, a joint distribution over the four quarters' points for
both teams, from point-in-time inputs only (games final before the
entry capture; the slate's history snapshot hashed before pricing;
a failed refresh fails the slate closed).

**Design-screen result of record** (design §5 criteria, fixed
before the run; 2023–2025, n = 1,632 team-games; both pre-declared
seeds): **SCREEN_PASS** — L1 pooled MAE(M) 4.40068 < B0 4.42281 and
< B1 4.46945; L2 M beats B0 in exactly 4 of 6 buckets (Q3, Q4, 1H,
2H); L3 Q4 leg 4.2324 < 4.2573; L4 stability leg holds in all three
seasons; no seed flip (seed-to-seed pooled difference ≈ 0.000002).
Panel integrity: 97.0% of team-games match finals exactly, 3.0%
differ only by overtime scoring, 0 unexplained. Disclosed screen
limitations carried into §0: the base-rate level shortfall, and a
mislabeled `safeties_per_game` aggregate in the results JSON (the
per-game rate is 0.045; the field divides by games without dividing
out replications) — the record stands as written. A screen is an
entry ticket, never validation; this forward test is the family's
verdict path, and its bar does not move whatever the screen said.

## 3. Settlement

Final period scoring (regulation only) from the nflverse schedules
record and the period panel machinery of the activation pack
(`research/nfl_activation_20261027/screen_nfl_activation_v1.py`,
sha256 `d8a11d8249c8142aa71062240ba92a799b4fa43ea0d2c7ffff757459460e568a`,
imported unmodified by the pinned engine for panel construction;
its integrity checks are re-run per slate, not assumed). A
postponed, suspended-and-not-completed, or cancelled game is
**void**: all its rows are excluded from every arm and counted in a
`VOID` report. A final period score equal to a row's graded line
is a **push**: counted, reported, excluded from win/loss
denominators (possible only on whole lines). If the settlement
source lacks a final for a game at review, the row is
`RESULT_UNAVAILABLE`: excluded and counted, never filled.

## 4. Universe, captures, pricing

- **Universe:** every paired DraftKings main period line (§1
  markets) for every game on each NFL slate, captured BEFORE
  kickoff — both sides of the same line from the same capture,
  timestamp recorded. One row per (game, market, team where the
  market is a team market).
- **Capture expansion is a precondition of this test** (unchanged
  from the V1 draft's §10): period lines move from issue-comment
  material to the priced per-game capture subset (entry and close),
  and the NFL intake grammar gains period line forms; until both
  land, this test cannot open and no rows exist under it. The
  expansion is lane work and does not alter any frozen family's
  capture subset.
- **Entry:** the lane's **T-1H write** for the game (the first
  check run landing 75–45 minutes before start, per the lane's
  standing two-mark cadence) is the capture designated ENTRY for
  this family: the first DK capture so designated at the main
  period line. Later captures never replace or add entry rows
  (§14, FLAG 6).
- **Committed per-row record** (before kickoff, create-only): game,
  market, team (where applicable), line, both prices + capture
  timestamp, the construction's period distribution summary (mean
  and both-side probabilities), the emitted baseline references
  (§7b — the Lane A derivative's emitted mean for 1H markets, the
  B0 reference mean for quarter markets), pick classification (§6),
  entry no-vig probabilities, and the sha256 set (this document,
  engine, history snapshot).
- **Closing capture:** the lane's **FINAL write** for the game
  (the first check run landing within 20 minutes before start) is
  the closing capture, read under §8's validity rule — for period
  markets exactly as for full-game markets: **the close is a
  pre-kickoff object**. (A Q1 line trades in-play after kickoff;
  this test never reads an in-play price. Its baseline is the last
  pre-kickoff quote, which is the price the market set with the
  same information the construction had.)

## 5. Slates and gates (minimums) and the single review

- A slate is one NFL game date's captured board. A slate is
  **full** for a market when its pricing run covered that game
  day's full DK period board (the V1 draft's §4 rule). A partial
  slate's valid rows still count toward the row and game gates;
  the slate itself does not count toward the slate gate (the NFL
  team-totals slate rule, adopted).
- Per market (never pooled): **≥100 graded rows AND ≥40 distinct
  games AND ≥4 full slates** priced under the frozen package.
  **These gates are minimums, not caps** (owner clarification,
  Oct 22, 2026: "40 / exactly 40 distinct games per market" is a
  minimum verdict-review gate; rows beyond the minimum at the
  review close are included, nothing is trimmed). Justification:
  the 100-row / 40-game floors are the Part 2 verdict floors for a
  single market (with the INSUFFICIENT_SAMPLE rule below 100 rows),
  adopted because a period market's rows accrue at the same
  per-game rate as a Part 2 prop market's — one row per game per
  market — and its rows share game scripts the same way. Markets
  that never reach their floors report `INSUFFICIENT_SAMPLE`; the
  program does not lower a floor to manufacture a verdict.
- **The verdict review for each market happens once, at the first
  slate close where that market's gates are met** (the program's
  anti-peeking rule). The rows graded at that point are the sample
  of record. No review is rerun at a later count unless a new
  version preregisters it. No interim looks at primary metrics
  before that point (operational monitoring — capture counts,
  refusal counts, missing-close counts — is allowed and reports no
  accuracy or CLV figures).

## 6. Pick rule (fixed at freeze)

For totals and team totals: gap = model mean − entry line; PICKED
at |gap| ≥ **1.5 points** for quarter markets and ≥ **2.0** for 1H
markets. Justification: quarter scoring σ ≈ 5.5–6 points and 1H
σ ≈ 8 (from the activation screen's period panel, 2023–2025), so
both thresholds are ≈ 0.25σ — the same relative stringency class
as the sibling families' pick rules. For spreads: gap on the
home-margin scale, same thresholds. For moneylines: PICKED when
the model's win probability exceeds the entry no-vig probability
by ≥ **0.04**. Changing any threshold after the freeze is a new
version.

## 7. Primary test (per market; all legs required)

Row set: all legs use the same priced rows. A row whose close
fails validity (§8 — checked **before** any moved classification)
is excluded from §7a–§7c and counts toward the §8 insufficient-close
limit.

- **7a. CLV (primary).** Mean CLV (no-vig probability points, close
  minus entry, on the model-selected side per the construction's
  probabilities; every priced row is scored on its model-favored
  side, ties recorded `TIE` and excluded from the denominator, per
  Part 2) over rows with a valid same-line close. Required: the
  game-clustered interval at the §10 level lies **entirely above
  0**.
- **7b. Accuracy vs the existing model.** On the same rows: the
  construction's period means must beat, on MAE against realized
  period scoring, the Lane A surface as it stands at freeze —
  `sportsedge/team_half_pricing.py`'s derivatives for 1H markets
  (its TOTAL_1H / SPREAD_1H / TEAM_TOTAL_1H outputs are UNFITTED
  0.50-scale research pricers; beating them is necessary, not
  sufficient) and, for quarter markets, the league-share
  decomposition B0 of the design screen (no Lane A quarter-total
  pricer is live — the one that existed failed its harness and is
  retired; B0 is the standing baseline rather than a retired
  construction dressed as the incumbent). Required: upper bound of
  the §10 interval for ΔMAE below 0.
- **7c. Calibration.** Model probabilities by decile including the
  extreme decile, reported with every readout; a market whose top
  decile states ≥ 0.80 and realizes ≤ 0.60 at the verdict review
  is `DOES_NOT_BEAT_MARKET` on calibration grounds regardless of
  §7a (the overconfidence check the Part 2 readout carries, given
  teeth here because period markets invite extreme stated
  probabilities on short samples — stated in advance, not invented
  at review).

## 8. Close validity and the v1.1 moved-row rules

These are the frozen Part 2 missing-close rules (§4.5 of that
test) **as amended by the NFL props v1.1 close rule** (owner
ruling, Oct 22, 2026), verbatim in substance:

- **A close is readable (valid) only if** it is the same game,
  market, team, and **line** as the entry, carries both prices,
  and is captured **before kickoff and no more than 60:00 before
  kickoff** (exactly 60:00 is valid; at/after kickoff is not a
  close). Validity checks (timing, two-sidedness, line identity)
  run **before** any moved classification; a row with no valid
  close is a capture failure or a moved row per the reasons below,
  never both.
- **CLV_MISSING reasons — exactly one per row**, never filled in
  from another time or source, excluded from CLV means and never
  zero-filled: `NO_CLOSE_ROW` (nothing for that game/market/team
  in the close capture), `CLOSE_SINGLE_SIDED`,
  `CLOSE_NOT_PREKICKOFF`, `CLOSE_STALE` (captured more than 60:00
  before kickoff), and `LINE_MOVED` (a valid two-sided pre-kickoff
  close exists, only at a different line). A moved line is never
  repriced to the closing line and never read from an alternate
  ladder.
- **The 20% trip counts only true capture failures** (the v1.1
  amendment's change to Part 2's original all-reasons count): if
  more than 20% of a market's priced rows are CLV_MISSING for the
  four capture-failure reasons (`NO_CLOSE_ROW`,
  `CLOSE_SINGLE_SIDED`, `CLOSE_NOT_PREKICKOFF`, `CLOSE_STALE`),
  that market's verdict is `INSUFFICIENT_CLOSE_DATA`, whatever its
  row count. `LINE_MOVED` rows do **not** count toward the trip;
  they are governed by the moved-row test below. The CLV_MISSING
  share per market, broken down by reason, is reported with every
  readout.
- **Moved rows are a separate bucket and a second verdict test**
  (the v1.1 rule): `LINE_MOVED` rows form their own bucket, each
  recording its move direction — **favorable** or **adverse** —
  relative to the model-selected side; no repricing, no model.
  Primary CLV (§7a) is computed on same-line rows only and must
  pass on its own. In addition, moved rows face a **one-sided
  exact sign test** of adverse vs favorable moved rows at the §10
  level (α/k): if the test gives p < α/k in the adverse direction,
  the market's verdict is `DOES_NOT_BEAT_MARKET` regardless of
  §7a–§7c — lines do not move at random, and dropping moved rows
  from CLV would drop the worst CLV evidence and flatter the test
  (the ruling's stated reasoning). If there are zero moved rows,
  the sign test is not run.
- **Moved share cap:** if moved rows are **more than 50%** of a
  market's priced rows, that market's CLV verdict is labeled
  **`LOW_COVERAGE`** and cannot open PLAY by itself (the v1.1
  ruling's label; §14, FLAG 1 records the team-totals prereg's
  different instantiation of this cap for the freeze review).

## 9. Verdicts

Per market: `BEATS_MARKET` iff §7a AND §7b AND §7c all hold and
the §8 moved-row test does not fire; otherwise
`DOES_NOT_BEAT_MARKET`; `INSUFFICIENT_SAMPLE` /
`INSUFFICIENT_CLOSE_DATA` per §5/§8. A `BEATS_MARKET` verdict is
the market's pass under the Oct 27, 2026 validation law; it
changes no registration or eligibility by itself, and PLAY faces
the program's α = 0.05/k accounting. A failed verdict is a result,
not a defect to be tuned away: the construction may return only
as a new version under a new preregistration, scored from its own
freeze forward.

## 10. Multiple testing and intervals

Game-cluster bootstrap, **10,000 resamples**, seed fixed and
recorded at freeze (this revision proposes **20261028**, the NFL
team-totals precedent and the construction's screen seed A — the
freeze record confirms or replaces it before any row is priced),
intervals two-sided at level **1 − α/k**, α = 0.05, **k = the
number of families validated or under active forward test in the
program at verdict time** (recorded at freeze and at review; the
larger k governs). Verdicts are per market; the family's k
accounting counts the family **once, not once per market** (the
anti-peeking one-review rule is what disciplines the per-market
multiplicity, and it is stated here so the choice is auditable).
The §8 sign test is read at the same α/k level (§14, FLAG 2).

## 11. Missing-CLV accounting and fail-closed refusals

- Every readout reports, per market: graded rows; distinct games;
  CLV_MISSING count and share by reason; moved-row count, share,
  and direction split; mean CLV with its §10 interval; §7b ΔMAE
  with its interval; calibration deciles incl. the extreme decile.
  Excluded-and-counted codes: `RESULT_UNAVAILABLE`, `VOID`,
  `PUSH`, `TIE`. Any code not declared in the frozen package that
  appears at review is itself a defect and blocks the verdict
  (`UNDECLARED_REFUSAL_CODE`). A malformed row is refused alone; it
  never aborts the slate.
- **Not-yet-frozen refusal (in force from this revision until the
  freeze act):** the framework config carries
  `model_version: "UNPINNED"` — a sentinel no row can match — and
  the framework refuses every row whose `model_version` differs
  from the config's, so no row can be priced or counted under this
  family while it is unfrozen. The counted entry points of any
  forward runner built for this family must refuse by name with
  **`NFL_PERIOD_FORWARD_NOT_FROZEN`** until the freeze act lands
  (the naming follows the sibling period family on main,
  `NBA_PERIOD_FORWARD_NOT_FROZEN` in
  `sportsedge/nba_period_forward.py`, and the EFV2 precedent
  `EF_V2_FREEZE_NOT_AUTHORIZED`). After the freeze, a row carrying
  a different version string than the §2 pin is refused
  `MODEL_VERSION_MISMATCH` (the frozen team-totals runner's code).
  There is no caller-controlled bypass.

## 12. Integrity bindings

Document, config, engine, and inputs committed before the first
row is priced under the frozen test; captures paired, timestamped,
pre-kickoff; no retrospective additions; closes never backfilled;
historical rows (everything priced before the freeze) graded as
history where graded at all and never counted. Role/injury news is
recorded as context; the construction consumes none of it unless
its own committed design says so (this design says it does not).
Each slate's run record must prove it executed the frozen hashes,
or the slate does not count.

## 13. Version rules

The engine, constants, pick rule, and evaluator surface are fixed
by sha256 at the freeze commit. Any change after the freeze is a
**new version** under a new document, scored only from its own
freeze forward. Frozen text is never edited; amendments supersede
by reference.

## 14. REVIEW FLAGS (choices this draft makes visibly; the freeze review must close each)

- **FLAG 1 — Moved-share cap consequence.** The Oct 22, 2026 v1.1
  ruling labels a market with >50% moved rows `LOW_COVERAGE`
  (cannot open PLAY by itself); the frozen NFL team-totals
  preregistration instantiates the same cap as
  `INSUFFICIENT_CLOSE_DATA` for moved PICKED rows. §8 follows the
  ruling's `LOW_COVERAGE` label (this family's own draft §6
  promised the v1.1 rules "verbatim in effect"). The freeze
  review must confirm the label, because the two precedents in
  force differ.
- **FLAG 2 — Sign-test level.** The Oct 22, 2026 ruling's text
  fixes the moved-row sign test at α = 0.05; the V1 draft's §6 and
  the frozen team-totals preregistration read it at α/k. §8/§10
  draft α/k (the family's own §10 accounting governs every
  interval in this test, and an unadjusted α = 0.05 second test
  would sit outside it). The freeze review must confirm.
- **FLAG 3 — No forward runner exists yet.** The §2 engine pin is
  the construction implementation of record — a research screen
  script, not a fail-closed forward runner. No
  `sportsedge/nfl_period_*` forward module exists on main; refusal
  today is effected by the config's `UNPINNED` sentinel and the
  framework's version check (§11). The freeze cannot execute
  until a forward runner is built from the pinned construction
  (emitting the §4 per-row record, raising
  `NFL_PERIOD_FORWARD_NOT_FROZEN` pre-freeze and
  `MODEL_VERSION_MISMATCH` post-freeze), pinned by sha256 in the
  freeze record alongside the engine, and independently reviewed.
  If the runner rather than the screen implementation becomes the
  priced artifact, the §2 pin string must be re-struck at the
  freeze act on the exact freeze head.
- **FLAG 4 — Config flip timing.** Design §8 says the framework
  config keeps `model_version: "UNPINNED"` "until that revision."
  This revision **names** the pin string (§2) but deliberately
  does not edit the config: under the team-totals precedent the
  config's `model_version` and status flipped in the freeze act's
  own commit set, and flipping the version here — while the status
  still reads DRAFT — would weaken the fail-closed posture this
  revision exists to preserve. The freeze review must confirm
  this reading.
- **FLAG 5 — B0's forward form.** §7b's quarter baseline is the
  design screen's B0: the frozen sibling's full-game mean ×
  point-in-time league shares. The screen fit those shares
  walk-forward on strictly prior seasons under its recorded
  readings. Forward, §4 requires the B0 reference mean emitted per
  row at entry; the share table producing it must be fit on games
  final before the entry capture (the sibling sample rule:
  same-season priors supplemented by prior-season games) and its
  hash committed in the run record. That forward share-fit
  procedure is drafted here by analogy to the screen's readings —
  it is not text the V1 draft or the design fixes — and the freeze
  review must confirm it before the first counted slate.
- **FLAG 6 — Entry/close designation mapping.** The V1 draft names
  "the first DK capture designated ENTRY" and "the final
  pre-kickoff capture" as the close; §4 maps those onto the lane's
  standing two-mark cadence (ENTRY := the T-1H write, CLOSE := the
  FINAL write). The mapping is the only reading under which the
  lane's cadence and the draft's designations coincide, but
  capture expansion (§15) could land with a different subset
  shape; if it does, this mapping must be re-confirmed at freeze,
  not silently re-read.

## 15. Freeze checklist (owner) — all items open

- [ ] Capture expansion landed (period board in the priced subset,
      entry + close) and intake grammar extended, with parser
      tests.
- [ ] Forward runner built from the pinned construction, pinned,
      and refusing per §11 (FLAG 3).
- [ ] Independent review (CLEARED) of the frozen revision — this
      document as frozen — closed on the exact head carrying the
      freeze act, with §14's flags each closed on the record.
- [ ] Bootstrap seed (§10) and the §10 k list recorded in the
      freeze record.
- [ ] Freeze by owner ruling naming the first counted slate. No
      primary metrics (§7) are computed on forward rows before
      then.

*Revision draft prepared Oct 28, 2026, on main `be8d19a1e`. Not
frozen; not freezable until §15's items close. The V1 draft
remains the family's draft of record until a freeze act adopts
this revision; this document changes nothing by landing.*
