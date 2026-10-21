# PREREGISTRATION (DRAFT) — MLB pitcher outs: forward test vs captured DraftKings prices

**Status: DRAFT — NOT FROZEN, NOT IN FORCE.**
This draft was prepared Oct 20, 2026 under the owner's directive that every
family be carried to a verdict ("keep building to point everything is
validated"). It follows the structure of the FROZEN NFL props Part 2
preregistration (`research/nfl_props_part2_20261018/PREREG_NFL_PROPS_PART2_FORWARD_V1.md`),
whose rules it adopts without alteration. **Freezing is the owner's act,
per family. No game, row, or slate counts toward this test before its
freeze.** Rows priced before a freeze are historical record, never
prospective entries. Nothing in this draft changes the family's
registration, eligibility, or validation state, and no verdict issued
under it creates a PLAY.

Framework config: `sportsedge/forward_validation/configs/mlb_pitcher_outs.json`
(sport MLB, family PITCHER_OUTS, market PITCHER_OUTS). At freeze, this
document and that config freeze together; the config's sha256 is stamped
into every verdict record the framework emits.

## 1. The construction bound

Engine: the wired pitcher joint empirical-Bayes engine (MLB_PITCHER_JOINT_EMPIRICAL_BAYES) via mlb_phone_pitcher_pricing. Coverage boundary, stated plainly: the four sibling pitcher markets (PITCHER_K, PITCHER_BB, PITCHER_ER, PITCHER_HITS_ALLOWED) are ALREADY covered by a committed preregistration — docs/MLB_PITCHER_PROP_PROMOTION_PREREG.md (v2, Oct 4, 2026), a one-shot study over the archived 2026 PIT quote archive with a >= 150 graded-unit gate, run once after the 2026 postseason. They are deliberately NOT drafted here (no duplicate instruments). PITCHER_OUTS was not in that study's market set, so it takes the standard forward-test draft below. The card-side pitcher-K unit ledger (graded nightly) is an operative record, not a validation instrument, and is unaffected.

The version bound by this test is the config's `model_version`
(`mlb_pitcher_joint_empirical_bayes_v1`, engine `MLB_PITCHER_JOINT_EMPIRICAL_BAYES`). The evaluator refuses any
priced row carrying a different version string
(`MODEL_VERSION_MISMATCH`): every model version is scored AS IT STOOD
when it priced the games, and a changed construction is a new version
with its own preregistration and its own clock — never a silent
continuation of this one.

## 2. Universe, captures, pricing

- **Universe:** every paired DraftKings main-line offering in this
  market for every event in the family's priced population, captured
  BEFORE the event starts — paired meaning both sides of the same line
  from the same capture, with the capture timestamp recorded.
- **Captures:** Operative paired DraftKings capture for the game: an ENTRY capture before first pitch and a CLOSE capture that is the last capture before first pitch and no more than 60 minutes before it (the Capture Spec V1 close rule applied to first pitch). The archived MLB_PROP_PIT quote archive is the corpus of the pitcher promotion preregistration (docs/MLB_PITCHER_PROP_PROMOTION_PREREG.md) and is NOT this test's price source.
- **Line scale:** realized value = outs recorded by the pitcher in the game (official boxscore; 3 outs per full inning); line = the DK line. The framework stores `line` on this scale;
  the over-side (`OVER`) wins iff the realized value exceeds it,
  the other side iff it falls short, and equality is a push (graded,
  excluded from the win/loss denominator).
- **Priced records:** one record per priced row under the framework
  contract (`sportsedge/forward_validation/README.md`): event, subject,
  line, the model's probabilities for both sides, both entry prices with the entry capture timestamp, the model version string, and the
  record's own timestamp, written before the event starts. A record
  written after its event starts is historical by definition and is
  excluded from all verdict math.
- **Closing capture:** the final pre-start capture supplies closing
  prices; attachment matches on (event, subject, market, line) under
  the frozen missing-close rule (Section 4).

## 3. Scoring

Scoring is the framework's (`sportsedge/forward_validation/`), identical
in discipline to the frozen Part 2 readout:

- **CLV (PRIMARY):** for the model-selected side (higher EV at the entry prices; an exact tie is recorded TIE and excluded), CLV = closing
  no-vig probability − entry no-vig probability. The
  market's mean CLV is reported with a 95% CI from the block bootstrap
  clustered by event (the frozen evaluator's `boot`, seed and resample
  count unchanged).
- **Win/loss (secondary):** the model-selected side's result; pushes
  graded and shown separately.
- **Log loss:** the model's stated probability for the realized side,
  reported alongside the entry de-vigged DraftKings probability's log
  loss on the same rows.
- **Calibration:** model probabilities by decile, including the extreme
  (top) decile, per the Part 2 convention.
- **CRPS:** reported where the family's priced records carry
  engine-supplied candidate and baseline CRPS values; the framework
  never invents distribution math of its own.

## 3.1 Family-specific notes

A pitcher who does not start the game is never priced (the book voids the row and so does this test); early-exit and hook context is annotation only — the construction consumes none of it.


## 4. Sample size and verdicts — DRAFT terms

- **No verdict review before ALL of:** 150 graded rows; 40 distinct events.
- **INSUFFICIENT_SAMPLE:** fewer graded rows or distinct events than
  the gates above — no verdict for this market, whatever the point
  estimates say.
- **Missing-close rule (frozen text, adopted verbatim in effect):**
  a row whose two-sided close cannot be read at the final pre-start capture is `CLV_MISSING` — it stays in the win/loss count, is left out of the CLV average, and is never filled in from another time, line, or source. A close is readable only if it is the same event, subject, market, and line as the entry, carries both prices, and is captured before the event starts and no more than 60 minutes before it. Every CLV_MISSING row carries exactly one reason: `NO_CLOSE_ROW`,
  `LINE_MOVED`, `CLOSE_SINGLE_SIDED`, `CLOSE_NOT_PREKICKOFF`, or
  `CLOSE_STALE`. If more than 20% of the market's rows are CLV_MISSING,
  the market's CLV verdict is `INSUFFICIENT_CLOSE_DATA`.
- **Verdict:** `BEATS_MARKET` iff the event-clustered 95% CI for mean
  CLV lies entirely above 0; otherwise `DOES_NOT_BEAT_MARKET`. The
  burden of proof is on the model. Verdicts are per market, never
  pooled.
- **Every readout reports:** graded rows; distinct events; CLV_MISSING
  count, share, and breakdown by reason; mean CLV with its clustered
  CI; win/loss with pushes shown; log loss (model and de-vigged DK);
  calibration deciles including the extreme decile; exclusions
  (historical rows, late entries, unscored rows) by id.

## 5. Integrity bindings

- Document, config, engine build, and inputs are committed before the
  first row is priced under the frozen test; the freeze commit's hashes
  are the test's identity.
- Captures are paired, timestamped, pre-start; a capture that misses
  the event start is excluded and the exclusion is recorded.
- No retrospective additions and no backfilled closes: a row not
  committed before its event, and a close not captured in the close
  window, do not exist for this test.
- Historical rows (including every row priced before the freeze) are
  graded as history where graded at all and never count toward this
  test's sample, gates, or verdicts.
- Role, lineup, and injury news is recorded alongside rows as context;
  the construction consumes none of it unless its own committed design
  says so.
- A failed verdict is a result, not a defect to be tuned away: the
  construction may return only as a NEW version under a NEW
  preregistration, scored from its own freeze forward.

*Draft prepared Oct 20, 2026 (Rocky), under the forward-validation
program: `research/forward_validation_program_20261020/PROGRAM.md`.*
