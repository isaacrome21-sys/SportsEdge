# PREREGISTRATION (DRAFT) — NFL team totals: forward test vs captured DraftKings prices

**Status: DRAFT — NOT FROZEN, NOT IN FORCE.**
Prepared Oct 27–28, 2026 in the NFL activation pack
(`research/nfl_activation_20261027/`), under the owner's directive that
every family reach clock-running, armed, or screening. It follows the
four-leg test architecture of the frozen NBA team-totals
preregistration (`research/nba_team_totals_forward_20261022/PREREG_NBA_TEAM_TOTALS_FORWARD_V1_DRAFT.md`)
and the capture rules of the frozen NFL props Part 2 test
(`research/nfl_props_part2_20261018/PREREG_NFL_PROPS_PART2_FORWARD_V1.md`),
which it adopts except where a deviation is stated and justified.
**Freezing is the owner's act. No game, row, or slate counts toward
this test before its freeze.** Rows priced before a freeze are
historical record, never prospective entries. No verdict issued under
this test creates a PLAY.

Framework config: `sportsedge/forward_validation/configs/nfl_team_total.json`
(sport NFL, family TEAM_TOTAL, market TEAM_TOTAL). At freeze, this
document and that config freeze together; the config's sha256 is
stamped into every verdict record the framework emits.

## 0. Up-front risk: the implied-split diagnostic

Read this before anything else. The construction's design screen
(`SCREEN_REPORT.md`) beat the naive baselines (pooled MAE 7.749 vs
team-mean 7.831 / league-mean 7.924) and **lost to the implied split
of the nflverse closing snapshot (7.250)** — the (total ∓ spread)/2
decomposition of two traded lines. The DraftKings closing team-total
line this test must beat is at least that strong. The prior
expectation, stated before any forward row exists, is that §6a (the
governing accuracy leg) is the leg most likely to fail, exactly as
the NBA team-totals preregistration disclosed for its own family. A
failure of §6a is `DOES_NOT_BEAT_MARKET`, recorded as such, and may
not be explained away by the naive-baseline wins.

## 1. The construction bound

Engine: `NFL_TEAM_TOTAL_DIST_V1` as specified in
`DESIGN_NFL_TEAM_TOTALS_V1.md` (same pack): point-in-time samples
(same-season priors supplemented by prior-season games to 8), league
pool mean G, K = 3 shrinkage, multiplicative opponent adjustment
μ_T = off_T · def_O / G, Negative Binomial distribution with pooled CV
c from the 2018–2019 training seasons only. The engine takes **no
market input**. The version bound by this test is the config's
`model_version`, pinned by sha256 at freeze; the runner refuses any
priced row carrying a different version string
(`MODEL_VERSION_MISMATCH`). A changed construction is a new version
with its own preregistration and its own clock — never a silent
continuation of this one.

**Design screen:** PASS vs the naive baselines under the criteria
fixed in `screen_nfl_activation_v1.py` before the run (full record:
`SCREEN_REPORT.md`). A screen is an entry ticket, never validation;
this forward test is the family's verdict path, and its bar does not
move whatever the screen said.

## 2. Universe, captures, pricing

- **Universe:** every paired DraftKings main team-total line (the
  primary line for each team, not an alternate) for every game on
  each NFL slate, captured BEFORE kickoff — paired meaning both sides
  (over and under) of the same line from the same capture, with the
  capture timestamp recorded. `TeamTotal` is already in the NFL
  intake grammar and Capture Spec V1's scope; no expansion is
  required.
- **Entry:** the first DK capture designated ENTRY for the game at
  the main team-total line (the NBA team-totals entry rule, adopted:
  later ENTRY captures and alternate lines never replace or add
  rows). One row per team per game.
- **Committed per-row record** (written before kickoff, create-only):
  game, team, line, both DK prices + capture timestamp, μ_T, the
  emitted B1 (team sample mean) and B2 (league mean G) reference
  means, model probabilities for both sides, fair odds, EV for both
  sides, the pick classification (§5), entry no-vig probabilities
  (multiplicative de-vig), and the sha256 of this document, the
  engine file, and the slate's history snapshot.
- **Closing capture:** the final pre-kickoff capture for the game
  supplies closing prices under the readability rule of §7.

## 3. Settlement

Final team points (including overtime, per DK settlement) from the
nflverse schedules record, joined on game_id. A postponed,
suspended-and-not-completed, or cancelled game is **void**: all its
rows are excluded from every arm and counted in a `VOID` report. A
final score equal to a row's graded line is a **push**: counted,
reported, excluded from the hit-rate leg (§6d). If the settlement
source lacks a final for a game at review, the row is
`RESULT_UNAVAILABLE`: excluded and counted, never filled.

## 4. Slates and gates (minimums) and the single review

- A slate is one NFL game date's captured board. A slate is **full**
  when both its ENTRY and CLOSE capture jobs ran for that date and
  every game on the date's DK board was captured (games with no DK
  team-total offer count as captured and go to the missing-offer
  report). A partial slate's valid rows still count toward the row
  and game gates; the slate itself does not count toward the slate
  gate.
- **Gates are minimums: ≥4 full slates AND ≥150 engine-priced rows
  with valid close pairing AND ≥40 distinct games AND ≥50 picked
  rows.** Justification (not borrowed silently): an NFL slate carries
  up to 32 team-total rows, so 150 rows ≈ 5 full slates of
  accumulation — the same order as the NBA team-totals gates (150
  rows / 40 games / 50 picked) against a comparable per-slate row
  supply; the 40-distinct-games floor is the program's standing
  minimum-gate convention (the Oct 22, 2026 clarification: a minimum
  verdict-review gate, not a cap).
- **The verdict review happens once, at the first slate close where
  all gates are met.** The rows graded at that point are the sample
  of record; rows beyond the minimums are included, nothing is
  trimmed. No review is rerun at a later count unless a new version
  preregisters it. No interim looks at the primary metrics before
  that point (operational monitoring — capture counts, refusal
  counts, missing-offer counts — is allowed and reports no accuracy
  or CLV figures).
- **Missing-offer games** are listed per slate in a `MISSING_OFFER`
  report with capture id and timestamp, never backfilled from another
  book, a later capture, or a derived split, and never counted in any
  denominator.

## 5. Pick rule (fixed at freeze)

`gap = μ_T − entry_line`. PICKED OVER if `gap ≥ +2.0` points, PICKED
UNDER if `gap ≤ −2.0`; otherwise PASSED. Justification: a team's
score standard deviation is ≈ 10 points (the screen's pooled CV of
0.4644 at a league mean near 22 implies σ ≈ 10.2), so ±2.0 ≈ 0.2σ —
the same relative stringency as the NBA team-totals ±2.0 pick rule
(≈0.18σ of its team-total σ). Changing the threshold after the freeze
is a new version.

## 6. Primary test (all four legs required)

Row set: all legs use the same engine-priced rows. A row whose close
fails validity (§7 — checked **before** any moved classification) is
excluded from §6a–§6d and counts toward the insufficient-close limit:
if >20% of engine-priced rows lack a valid close, the verdict is
`INSUFFICIENT_CLOSE_DATA`.

- **6a. Accuracy vs the market baseline (governing).** Paired per row
  against final team points: ΔMAE_mkt = MAE(engine mean) −
  MAE(close line), the close line being the line of that row's valid
  close. Required: the upper bound of the §9 interval for ΔMAE_mkt
  lies **below 0**. RMSE difference reported alongside.
- **6b. Accuracy vs the existing model (Lane A).** Same rows, same
  interval: the engine's mean must beat the mean Lane A emitted for
  the same team-game at entry time (Lane A is hash-pinned at freeze;
  its emitted team-total means are recorded in the run record).
  Required: upper bound of the interval for ΔMAE_LaneA below 0. A
  construction that beats DraftKings but not the program's own
  existing model has not earned the label the Oct 27, 2026 law
  defines, and this leg says so.
- **6c. CLV.** Every row is scored on side sign(gap) (gap = 0 rows
  excluded and counted as `GAP_ZERO`). Required: mean CLV on PICKED
  rows > 0 with the §9 lower bound above 0, AND picked mean CLV >
  mean CLV of PASSED rows scored on their sign(gap) side. CLV is
  computed only on rows whose valid close is at the entry line.
  Moved rows (valid two-sided pre-kickoff close only at a different
  line) are reported separately with the one-sided exact sign test of
  favorable vs adverse movement, as in NFL props v1.1.
- **6d. Hit rate vs the market.** Only PICKED rows whose valid close
  is at the entry line; the hit is graded **at the entry line**.
  Metric: hit − p_close, p_close the vig-free close probability of
  the picked side from the two-sided close pair at the entry line
  (for whole-number lines, conditional on no push; pushes excluded
  and counted). Required: mean > 0 with the §9 game-clustered lower
  bound above 0.

**Moved-row rules (matching NFL props v1.1), checked first, in
order:** (1) if the one-sided exact sign test of adverse vs favorable
moved PICKED rows gives p < α/k in the adverse direction, the verdict
is `DOES_NOT_BEAT_MARKET` regardless of §6a–§6d; (2) else if more
than 50% of PICKED rows are moved rows, the verdict is
`INSUFFICIENT_CLOSE_DATA`. If there are zero moved picked rows, the
sign test is not run and rule 1 does not apply.

Only if neither applies: `BEATS_MARKET` requires **6a AND 6b AND 6c
AND 6d**.

## 7. CLV and close validity (capture rules)

- CLV = no-vig implied probability of the side at close minus at
  entry, each from a real matched two-sided pair at the **same
  line**.
- **Close:** the last capture before kickoff and **no more than
  60:00 before** kickoff (exactly 60:00 is valid; at/after kickoff is
  not a close). Pairing span and quote-freshness limits are the
  pinned runner's, declared at freeze and not altered by this draft.
- Validity checks (timing, two-sidedness, freshness, span) run
  **before** any moved classification; a row with no valid close is a
  capture failure, never a moved row.
- "Final" means final among records committed at review time; later
  commits never rewrite a pairing.

## 8. Missing CLV and fail-closed refusal codes

Exactly one reason per row; excluded from means, never zero-filled.
CLV-missing: `NO_CLOSE_ROW`, `LINE_MOVED`, `CLOSE_SINGLE_SIDED`,
`CLOSE_NOT_PREKICKOFF`, `CLOSE_STALE`, `PAIR_SPAN_EXCEEDED`,
`QUOTE_STALE_180S`. Excluded-and-counted: `RESULT_UNAVAILABLE`,
`VOID`, `PUSH`, `GAP_ZERO`. Engine/runner refusals (row never priced,
counted and reported) are the pinned runner's code set, listed in its
freeze pin. Any code not declared in the frozen package that appears
at review is itself a defect and blocks the verdict
(`UNDECLARED_REFUSAL_CODE`). A malformed row is refused alone; it
never aborts the slate.

## 9. Multiple testing and intervals

All intervals: **game-cluster bootstrap, 10,000 resamples**, seed
fixed and recorded at freeze, **two-sided at level 1 − α/k**,
α = 0.05. **k** = the number of families validated or under active
forward test in the program whose windows overlap this test's window,
counting this test from its freeze date; the clock/family list is
recorded at freeze and again at review, and the larger k is used.

## 10. Verdicts

- `BEATS_MARKET` — §6a, §6b, §6c, §6d all hold (subject to the
  moved-row rules). A `BEATS_MARKET` verdict is this family's pass
  under the Oct 27, 2026 validation law; it does not by itself change
  registration, eligibility, or promotability — any change is an
  owner ruling, and PLAY additionally faces the program's α = 0.05/k
  accounting across validated families.
- `DOES_NOT_BEAT_MARKET` — any leg fails. Per §0, a failure of §6a is
  the expected-risk outcome and is recorded as such.
- `INSUFFICIENT_CLOSE_DATA` per §6/§8.
- `INSUFFICIENT_SAMPLE` — the gates of §4 unmet at any earlier look;
  no verdict issues.

## 11. Version rules

The engine, runner, history-store pins, pick rule, and evaluator are
fixed by sha256 at the freeze commit. Each slate's run record must
prove it executed the frozen hashes, or the slate does not count. Any
change after the freeze is a **new version** under a new document,
scored only from its own freeze forward. Frozen text is never edited;
amendments supersede by reference.

## 12. Freeze checklist (owner)

- [ ] Engine build of `NFL_TEAM_TOTAL_DIST_V1` committed with the
      hash-pin discipline and independently reviewed (CLEARED by a
      checker who did not build it).
- [ ] Lane A's emitted-means recording verified in the run record
      (§6b depends on it).
- [ ] Bootstrap seed and the §9 k list recorded in the freeze record.
- [ ] This document frozen by owner ruling; the freeze record names
      the first counted slate as **the first slate priced after the
      engine pin is reviewed**. No primary metrics (§6) are computed
      on forward rows before then.

*Draft prepared Oct 27–28, 2026 (activation pack). Not frozen.*
