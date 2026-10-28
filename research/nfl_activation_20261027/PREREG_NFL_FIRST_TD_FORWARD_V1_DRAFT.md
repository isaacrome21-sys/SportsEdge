# PREREGISTRATION (DRAFT) — NFL first touchdown scorer: forward test vs captured DraftKings prices

**Status: DRAFT — NOT FROZEN, NOT IN FORCE, AND NOT FREEZABLE in this
pack.** The family's attribution panel does not exist yet (the design
doc's missing step 1); the construction's calibration screen (§1)
cannot run until it does, and no construction may be frozen under
this draft until the screen has run under the criteria fixed here and
been recorded. Terms are written now so the screen and the freeze are
decisions about the construction, not about terms fitted afterward.
**Freezing is the owner's act. No game, row, or slate counts toward
this test before its freeze.**

Framework config: `sportsedge/forward_validation/configs/nfl_first_td.json`
(sport NFL, family FIRST_TD, market FIRST_TD, `market_form: YES_ONLY`,
`model_version: "UNPINNED"` (a sentinel no row can match, so every row is refused fail-closed) until the construction is pinned). Structure:
the frozen anytime-TD selection and CLV forms, carried into this
program by the 2+ TD preregistration draft
(`research/forward_validation_program_20261020/drafts/PREREG_NFL_TWO_PLUS_TD_FORWARD_V1_DRAFT.md`),
whose missing-close and integrity rules this draft adopts verbatim in
effect. **This draft does not alter the frozen ATD v1.1 test in any
way** — different market, different construction, different clock.

## 1. The construction bound + the screen that must precede any freeze

Engine: `NFL_FIRST_TD_V1` as specified in
`DESIGN_NFL_GAME_PROPS_TD_V1.md` §2 (two-stage: team-first
probability × within-team first-scorer share with two-level
shrinkage; DEF/ST as a pooled outcome class; no-TD outcome carried;
no market input; point-in-time samples only).

**Calibration screen (pre-freeze, on the admitted attribution
panel, 2020–2025 design seasons — seen data; an entry ticket, never
validation).** Criteria fixed here, before the panel exists:
the construction must beat BOTH baselines on mean log loss over all
games in the panel — B1 (anytime-share-only: stage-2 shares replaced
by shrunk anytime TD shares, stage 1 unchanged) and B2 (league
positional pool only) — with the game-clustered 95% CI for each
log-loss difference entirely below 0, AND its top-decile stated
probabilities must not overstate realized frequency by more than
10 points (the extreme-decile calibration check of the Part 2
readout, at a bound stated in advance). A fail is `FAILED_SCREEN`:
the construction does not advance and returns only as a new version.

## 2. Universe, captures, pricing

- **Universe:** every player on DraftKings' first-TD-scorer board
  for every game on each NFL slate, captured BEFORE kickoff. The
  board is **YES_ONLY**: the Yes price is the complete quote; there
  is no second side to pair. **Capture expansion is a precondition:**
  the first-TD board joins Capture Spec V1's per-game subset (entry
  and close) before this test can open; today it is comment-only
  material. The expansion does not alter the anytime-TD board's
  capture or the frozen ATD test.
- **Identity:** a row is priced only if the player resolves to
  exactly one nflverse player_id at capture time (the Part 2 identity
  rule). Unresolvable rows are excluded and the exclusion recorded —
  identity is never guessed. A listed player who is inactive at
  kickoff still settles per DK (a loss if he does not score first);
  the row stays in the sample — scratch status is recorded as
  context, and the construction's pre-kickoff information state is
  the entry capture's, exactly as the frozen families treat role
  news.
- **Priced records:** one record per priced row under the framework
  contract: event, subject (player), the model's YES probability and
  the entry Yes price with entry capture timestamp, the model
  version string (refused at freeze-time pinning if mismatched), and
  the record's own timestamp, written before kickoff. A record
  written after kickoff is historical by definition and excluded
  from all verdict math.
- **Closing capture:** the final pre-kickoff capture supplies closing
  Yes prices; attachment matches on (event, subject, market) under
  §4's missing-close rule.

## 3. Scoring

- **Selection (locked ATD rule):** PICKED iff the model's YES
  probability exceeds the entry Yes price's raw implied probability.
  Every other priced row is PASS — reported with its own CLV read,
  never in the verdict sample.
- **CLV (PRIMARY):** for PICKED rows, closing raw implied probability
  − entry raw implied probability (YES_ONLY form; no de-vig exists).
  The known bias — DraftKings' cut drift counts toward the reading,
  most on longshots — is stated in every readout. Mean CLV with a
  95% CI from the block bootstrap clustered by event.
- **Win/loss (secondary):** the picked row wins iff the player is the
  game's credited first scorer per the official play-by-play
  attribution (defensive/return first TD ⇒ every player row loses;
  no-TD game ⇒ every player row loses). DK settlement governs
  payment; attribution differences are recorded per row.
- **Log loss:** the model's stated probability for the realized
  outcome over ALL priced rows (picked and passed), reported
  alongside the entry raw-implied log loss on the same rows.
- **Calibration:** model probabilities by decile including the
  extreme decile, per the Part 2 convention.

## 4. Sample size and verdicts — DRAFT terms

- **No verdict review before ALL of:** 100 graded PICKED rows (the
  verdict sample for a YES_ONLY market — the 2+ TD draft's gate,
  adopted because the accrual shape is identical: a handful of
  picked longshots per game); 40 distinct events; 4 full slates
  priced under the frozen package (a slate counts only if its
  pricing run covered that game day's full DK first-TD board).
- **INSUFFICIENT_SAMPLE:** fewer graded picked rows or distinct
  events than the gates — no verdict, whatever the point estimates
  say.
- **Missing-close rule (frozen text, adopted verbatim in effect):**
  a row whose Yes close cannot be read at the final pre-kickoff
  capture is `CLV_MISSING` — it stays in the win/loss count, is left
  out of the CLV average, and is never filled in from another time or
  source. A close is readable only if it is the same event, subject,
  and market, carries the Yes price, and is captured before kickoff
  and no more than 60 minutes before it. Every CLV_MISSING row
  carries exactly one reason: `NO_CLOSE_ROW`, `LINE_MOVED` (reserved
  — a Yes board has no line; the code is carried so the taxonomy is
  uniform across families and is expected to fire never),
  `CLOSE_SINGLE_SIDED`, `CLOSE_NOT_PREKICKOFF`, or `CLOSE_STALE`. If
  more than 20% of rows are CLV_MISSING, the verdict is
  `INSUFFICIENT_CLOSE_DATA`.
- **Verdict:** `BEATS_MARKET` iff the event-clustered interval (§5)
  for mean CLV on PICKED rows lies entirely above 0; otherwise
  `DOES_NOT_BEAT_MARKET`. The burden of proof is on the model.
- **Every readout reports:** graded picked rows; passed rows with
  their own CLV read; distinct events; CLV_MISSING count, share, and
  breakdown by reason; mean CLV with its clustered CI; win/loss;
  log loss (model and entry raw-implied) over all priced rows;
  calibration deciles including the extreme decile; exclusions by id.

## 5. Multiple testing and intervals

Game/event-cluster bootstrap, 10,000 resamples, seed fixed and
recorded at freeze, intervals two-sided at level 1 − α/k, α = 0.05,
k = the number of families validated or under active forward test in
the program at verdict time (recorded at freeze and at review; the
larger k governs).

## 6. Integrity bindings

Document, config, engine build, attribution-panel pin, and inputs
are committed before the first row is priced under the frozen test;
the freeze commit's hashes are the test's identity. Captures are
timestamped and pre-kickoff; a capture that misses kickoff is
excluded and the exclusion recorded. No retrospective additions and
no backfilled closes. Historical rows (including every row priced
before the freeze) are graded as history where graded at all and
never count toward this test's sample, gates, or verdicts. A failed
verdict is a result, not a defect to be tuned away: the construction
may return only as a new version under a new preregistration, scored
from its own freeze forward.

## 7. Freeze checklist (owner) — all items open

- [ ] Attribution panel built, hash-pinned, and admitted (design
      doc step 1), with exclusion counts reported.
- [ ] Calibration screen run under §1's fixed criteria and recorded
      (PASS required to proceed).
- [ ] Capture expansion landed (first-TD board in the priced subset,
      entry + close).
- [ ] Independent review (CLEARED) of the frozen revision; bootstrap
      seed and §5 k list recorded; freeze by owner ruling naming the
      first counted slate.

*Draft prepared Oct 27–28, 2026 (activation pack). Not frozen; not
freezable until §7's screen and capture items close.*
