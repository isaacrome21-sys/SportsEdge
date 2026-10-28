# BUILD RECORD — NBA period-lines forward wiring (2026-10-28)

**State: BUILT, NOT FROZEN, NO CLOCK, NO COUNTED ROWS.** This build is
the dispatch the period-lines preregistration draft
(`research/nba_cbb_activation_20261028/NBA_PERIOD_LINES_PREREG_DRAFT.md`,
PR #2843) names in its §6: it became dispatchable when the §4.1 feed
admission merged (PR #2880) and it supplies the §4.2 capture grammar.
Freezing the preregistration is the owner's separate act and is NOT
effected or requested here.

## What was built

1. **Engine wiring to the admitted feed** —
   `sportsedge/nba_period_forward.py`. Consumes `NBAPeriodObservation`
   records from the one admitted period-outcomes feed (ESPN summary
   API, `ESPN_SUMMARY_API` / `espn-summary-v1:20261028`, admitted by
   `research/nba_quarter_score_feed_admission_20261028/ADMISSION_RECORD.md`
   for DESIGN_SCREEN + FORWARD_GRADING_OUTCOMES +
   IN_SEASON_PRIOR_BASELINES only) in exactly the §4.1 form:
   - source/version must match the admission exactly, else
     `NBA_PERIOD_OBSERVATION_SOURCE_NOT_ADMITTED`;
   - exactly four regulation quarters per side, real ints only (bool,
     float and numeric-string entries refuse), else
     `NBA_PERIOD_OBSERVATION_FORM_INVALID`;
   - overtime periods are carried in the feed entries separately and
     never enter the quarter tuples (the pinned OT sample 401909877
     sums to 117 in regulation against a 125 final — asserted in
     tests);
   - halves are re-verified as the exact mechanical sums Q1+Q2 /
     Q3+Q4 (`NBA_PERIOD_HALF_SUM_MISMATCH`) and linescore sums against
     payload finals (`NBA_PERIOD_SCORE_MISMATCH`) on every manifest
     entry consumed;
   - unresolvable team tricodes refuse `NBA_PERIOD_IDENTITY_UNVERIFIED`
     (ESPN `GS` resolves to `GSW` through the repo's own conventions).
   In-season priors are engine rows dated strictly before the target
   game (ET game dates — a 02:30Z tip belongs to the prior evening's
   slate, so same-slate games never consume each other). Grading
   consumes the target game's observation post-final only, with teams
   and date proven against the priced record
   (`NBA_PERIOD_GRADE_IDENTITY_MISMATCH`).
2. **§4.2 DK capture-grammar extension** —
   `sportsedge/nba_period_lines_intake.py` plus twelve period market
   specs on the NBA adapter (`sportsedge/pipeline/adapters.py`):
   `Q1..Q4 Total`, `1H/2H Total` (game totals) and `<Team> Q1..Q4 TT`,
   `<Team> 1H/2H TT` (team totals), all parsing through the shared
   issue parser under its standing transcription discipline (both
   prices required, plain ASCII decimals, no coercion, duplicates
   refuse). A section DK does not post is declared
   `<label> NOT_OFFERED` and recorded as a NOT_OFFERED quote. The §4.2
   census is enforced per game: every window of every one of the four
   prereg subfamilies (team subfamilies for BOTH teams) must be priced
   or explicitly NOT_OFFERED, else `NBA_PERIOD_CAPTURE_INCOMPLETE`;
   priced-and-NOT_OFFERED refuses `NBA_PERIOD_SECTION_CONFLICT`.
   No capture-scope expansion: period sections ride the same lane
   issue bodies for NBA games already in coverage.
3. **Freeze rails.** Every counted entry point refuses by name:
   `price_period_game(..., counted=True)`, `price_counted_slate(...)`
   and `run_forward_test(...)` all raise
   `NBA_PERIOD_FORWARD_NOT_FROZEN`. The research pricing/grading path
   stamps `counted: False`, `state: NON_COUNTED`,
   `freeze_state: DRAFT_NOT_IN_FORCE`, `validation_credit: False`,
   `forward_clock_credit: False`, `play_eligible: False` on every
   record.

## Landing check (NON_COUNTED, `LANDING_CHECK.json`)

One historical slate priced and graded end to end from admitted-feed
data only: the 2015-04-15 (ET) slate — 14 games, the final day of the
2014-15 regular season — with priors from admitted-feed games dated
2015-03-20..2015-04-14 ET. The admission packet's pinned sample
(400579520, CHA @ TOR) was cross-checked against the merged manifest
before pricing (quarters and finals match: PASS) and was itself priced
and graded. A synthetic DK-style capture for that game (lines
constructed from finals, labeled synthetic in the record — NOT market
data) exercised the §4.2 grammar and settlement path: 18 quotes
recorded, 3 NOT_OFFERED (the Q3 sections), settlements stamped
counted=False.

Results (`LANDING_CHECK.json`, produced by `run_landing_check.py`):
212 entries pulled from the admitted route (2015-03-20..04-15
scoreboard discovery; summaries extracted by the admission packet's
own puller) with **zero pull refusals and zero form-gate refusals**;
198 history games; **all 14 slate games priced and graded**, no
sufficiency refusals (league priors 396 team-games, every slate team
at ≥ 10 priors). Aggregate MAE across the slate — TEAM_QUARTER_TOTAL
4.248 (n=112), GAME_QUARTER_TOTAL 6.102 (n=56), TEAM_HALF_TOTAL 6.632
(n=56), GAME_HALF_TOTAL 9.040 (n=28). These magnitudes sit in the
range of the Oct 20 calibration screen's (4.61 / 6.65 / 6.45 / 9.75)
but are NOT a reproduction of it: this walk's ratings state is built
from the late-season prior window only, and the numbers are wiring
evidence, not a screen result. An earlier landing run over a shorter
prior window (2015-03-25..04-14) priced 10 of 14 and recorded the
other four under the named refusal
`NBA_TEAM_PERIOD_INSUFFICIENT_TEAM_PRIORS` (four teams at 9 priors) —
the frozen sufficiency gate working as designed; the window was
widened for the final run, no gate was touched.

## Tests

- `tests/test_nba_period_forward_20261028.py` — form gate, source
  gate, cross-checks, ET-date/OT handling, NOT_FROZEN rails,
  NON_COUNTED price+grade end to end, identity-mismatch refusal,
  closing-quote settlement.
- `tests/test_nba_period_lines_intake_20261028.py` — full-census
  parse, NOT_OFFERED recording, incomplete/conflict/duplicate/
  unrecognized refusals, malformed-line refusals (one-sided, extra
  price, scientific notation, underscore, in-band price, subjectless
  team total, non-numeric line), render/parse round-trip, per-game
  census isolation on a two-game body.
- Regression surface run with this build: the period family suites,
  the admission-manifest guards, and the shared-parser consumers
  (cross-sport parity, exact prices, grading integrity, hostile
  boundaries, NHL/MLB/NFL/NBA intakes, numeric guards) — counts in the
  PR body.

## What this build does NOT do

- It does not freeze the preregistration, start a clock, count a row,
  or produce a screen/verdict. The §5 forward test still requires the
  owner's freeze and, from that date, T-1H/FINAL DK captures under
  the lane cadence (the grammar above is what those captures will
  use; no historical capture substitutes for them).
- The feed is not used as a pregame pricing input or in-play source
  (outside its admitted scope); the target game's quarters are
  grading labels only.
- Nothing here touches the NBA props V2 quarantine, the NBA team
  totals family, or any threshold, fit or registration state.
  PAPER / research only.
