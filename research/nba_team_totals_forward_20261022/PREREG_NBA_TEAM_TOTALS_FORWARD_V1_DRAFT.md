# PREREGISTRATION — NBA Team Totals Forward Test V1

# DRAFT — NOT FROZEN — NOT IN FORCE — NO GAMES COUNT

**This document is a draft pending (1) an independent review by a
checker who did not write it and (2) the owner's freeze. No game,
row, or capture counts toward this test until the owner freezes this
document (or a successor). Rows produced before the freeze are
historical record, never prospective entries. Nothing in this draft
changes any family's registration, eligibility, or validation state.**

- Status: `DRAFT_NOT_IN_FORCE` (revision 3: applies the NOT CLEARED reviews of
  `82b880ed` and `355db10d`; pending re-review + owner freeze)
- Date drafted: 2026-10-22
- Family in scope: NBA team total points (`TEAM_TOTAL`), registered
  2026-10-22 by owner ruling as `REGISTERED_RESEARCH_ONLY /
  NOT_VALIDATED`; eligible False, promotable False. PLAY is impossible
  under this test.
- Engine under test: `NBA_TEAM_PERIOD_RATINGS_V1`
  (`sportsedge/nba_team_period_engine.py`, merged in PR #2422; sha256 on
  main @ `ddf938894` =
  `9060b972f9d1f69696db7f75569ab175884e02ff7b6ea81fb9817c6f390bc6de`),
  team-total output only (`team_totals.home` / `team_totals.away`).
- Runner path: `sportsedge/research/nfl_nba_engine_card_annex.py`
  (PR #2431; sha256 on main @ `ddf938894` =
  `28edafba1e41baa4e0485d9c14542d4c8ba56d2a3913a8d22a546541fb13cbe2`)
  through `artifacts/run_it_full.py`.
- Structural model: NBA Props Forward V1 prereg (PR #2424,
  `research/nba_props_forward_20261020/PREREG_NBA_PROPS_FORWARD_V1.md`,
  sha256 `54363908b1e2332a57af9b9263ac2f398438c81b2d366442b80667086657bc79`).
- Out of scope: period totals (quarters/halves). Owner ruling
  2026-10-22: period totals wait until period lines are in the capture
  scope; they are not registered under this document.

## 0. Up-front risk: shared ratings model with a FAILED family

**Read this before anything else.** The team-total mean is the
predicted team points from the same ratings model
(`sportsedge/sports/nba/ratings_model.py` `NBARatings`, committed
defaults) that produces the NBA game-total mean. NBA game totals are
**FAILED_VALIDATION** on the record (accuracy gap first: game-total
RMSE model 21.46 vs DraftKings line 20.72; see
`research/nba_game_lines_forward_20261020/PREREG_NBA_GAME_LINES_FORWARD_V1_DRAFT.md` §1).
A team total is approximately one side's share of the game total, so
the prior expectation is that **the same accuracy gap repeats here**.

The engine's historical screen (`research/nba_team_period_20261020/REPORT.md`:
n=15,506, MAE 8.9975 vs team-mean 9.5411 / league-mean 9.8275) beat
**naive baselines only**. It never faced a market. That is why §6
makes the DraftKings close the governing baseline: a repeat of the
game-total failure must land here as `DOES_NOT_BEAT_MARKET`, and may
not be explained away by the naive-baseline wins.

The mean is not circular: the forecast function takes no market input;
the DK line enters only as the thing to beat. Inputs are strictly
earlier games (point-in-time, date granularity), gated fail-closed at
≥10 prior in-season games per team and ≥200 prior in-season league
team-games.

## 1. Question

Stated before any data is seen under this document: on the forward
2026-27 slates captured after the freeze, is the engine's team-points
mean **more accurate than the DraftKings closing team-total line**, and
do the rows it picks earn **positive closing-line value** against our
own DK captures?

## 2. Market

Exactly one family: `TEAM_TOTAL` — a single team's full-game points
(including OT, per DK settlement), two-sided OVER/UNDER at one line.
Every other market reaching the evaluator is refused
`MARKET_OUT_OF_SCOPE` and excluded from every denominator.

## 3. Data

Only the capture program's committed records (Capture Spec V1 as in
effect on main): sport, league, event/teams/start CT, market, team,
line, side, American price, book=DraftKings, `captured_at` with zone,
ENTRY/CLOSE designation, source view, entered_by. No fabricated,
retroactive, or backfilled prices.

**Settlement source.** Final team points (including OT, matching DK
settlement) come from the maintained sportsdataverse NBA team-boxscores
asset (the engine's own history path, `games_from_team_boxscores()`),
joined on game_id. If that asset lacks a final for a game at review,
the row is `RESULT_UNAVAILABLE`: excluded and counted, never filled.

**Void and push.** A postponed, suspended-and-not-completed, or
cancelled game is **void**: all its rows are excluded from every arm and
counted in a `VOID` report. A final score equal to a row's line is a
**push**: excluded from hit-rate (§6d) and the accuracy arms are
unaffected; pushes are counted and reported.

**Full slate.** A slate is full when both its ENTRY and CLOSE capture
jobs ran for that game date and every game on the date's DK board was
captured (games with no DK team-total offer count as captured and go to
the missing-offer report). A slate with a failed or partial capture job
does not count toward the slate gate (its valid rows still count toward
row and game gates).

**Missing-offer games.** When DraftKings offers no team total for a
game (e.g. the 2026-10-22 PM capture: none for 2 of 14 games), the
game is listed per slate in a `MISSING_OFFER` report with the capture
id and timestamp. It is **never backfilled** from another book, a later
capture, a derived game-total split, or any estimate, and it is never
counted in any denominator. The missing-offer count and share are
reported at review alongside the verdict.

## 4. Slates and gates (minimums) and the single review

- A slate is one NBA game date's captured board. Counting starts at
  zero with the first slate priced after the freeze **and** after the
  forward evaluator is pinned and independently reviewed (§12).
- Gates are **minimums**: ≥4 full slates AND ≥150 engine-priced rows
  with valid CLV pairing AND ≥40 distinct games AND ≥50 picked rows.
- **The verdict review happens once, at the first slate close where all
  gates are met. The rows graded at that point are the sample of record,
  and no review is rerun at a later count unless a new version
  preregisters it.** Rows beyond the minimums at that slate close are
  included; nothing is trimmed to hit a number.
- No interim looks at the primary metrics before that point. Operational
  monitoring (capture counts, refusal counts, missing-offer counts) is
  allowed and reports no accuracy or CLV figures.

## 5. Row rules

- League NBA, family `TEAM_TOTAL`, `team` bound to the fixture's home or
  away team (else `NBA_TEAM_SELECTION_UNBOUND`).
- **Entry definition.** The entry is the **first DK capture designated
  ENTRY for the game**, at the **main team-total line** (DK's primary
  line for that team, not an alternate). Later ENTRY captures and all
  alternate lines are ignored; they never replace or add rows.
- Side OVER/UNDER; numeric line; finite American price; both sides of
  the entry pair captured (runner refusals, §8).
- Engine stamp required: `engine_id = NBA_TEAM_PERIOD_RATINGS_V1`,
  `status = PRICED`, `sufficiency_met = true`, priors recorded. Rows
  without engine provenance are excluded and reported.
- **Pick rule (pending owner confirmation at freeze, §12):** `gap = mean − entry_line`.
  PICKED OVER if `gap ≥ +2.0` points, PICKED UNDER if `gap ≤ −2.0`;
  otherwise PASSED. One row per team per game. Changing the threshold
  after the freeze is a new version.

## 6. Primary test (all four legs required)

**Row set.** All legs use the same engine-priced rows. A row whose close
fails validity (§7; validity is checked **before** any moved
classification) is excluded from 6a–6d and counts toward the
insufficient-close limit: if >20% of engine-priced rows lack a valid
close, the verdict is `INSUFFICIENT_CLOSE_DATA`.

**6a. Accuracy vs the market baseline (governing).** On the same rows
in both arms, paired per row against final team points:

- `ΔMAE_mkt = MAE(engine mean) − MAE(close line)`, where the close line
  is **the line of that row's valid close** (§7), which may differ from
  the entry line.
- Required: the upper bound of the §9 interval for `ΔMAE_mkt` lies
  **below 0**. RMSE difference is reported alongside with the same
  interval.

**6b. Accuracy vs the construction's own baselines.** Same rows, same
interval: the engine must beat the emitted `home/away_team_mean` (B1)
and `league_mean` (B2) — the baselines its historical screen beat.

**6c. CLV.** Every row is scored on side `sign(gap)` (OVER if gap > 0,
UNDER if gap < 0; gap = 0 rows excluded and counted). Required: mean
CLV on PICKED rows > 0 with the §9 lower bound above 0, AND picked mean
CLV > mean CLV of PASSED rows scored on their `sign(gap)` side. CLV is
computed only on rows whose valid close is at the entry line. **Moved
rows** (valid two-sided pre-tip close only at a different line) are
reported separately: count, and a one-sided exact sign test of
favorable vs adverse movement relative to the picked side (direction
from the latest qualifying close; a row whose qualifying close lines
straddle the entry line counts as adverse), as in NFL props v1.1.

**6d. Hit rate vs the market.** Only PICKED rows whose valid close is
**at the entry line**; the hit is graded **at the entry line**. Metric:
`hit − p_close`, where `p_close` is the vig-free close probability of
the picked side from the two-sided close pair at the entry line. For
whole-number lines, `p_close` is the two-sided no-vig probability with
pushes removed (i.e. conditional on no push), and pushes are excluded
from the leg and counted (`PUSH`). Required: mean `hit − p_close` > 0
with the §9 game-clustered, Bonferroni-adjusted lower bound > 0.

**Moved-row rules (matching NFL props v1.1), checked first, in order:**
1. If the one-sided exact sign test of adverse vs favorable moved
   PICKED rows gives p < α/k in the adverse direction, the verdict is
   `DOES_NOT_BEAT_MARKET` regardless of 6a–6d.
2. Else, if more than 50% of PICKED rows are moved rows, the verdict is
   `INSUFFICIENT_CLOSE_DATA`.

Only if neither applies: `BEATS_MARKET` requires **6a AND 6b AND 6c AND
6d**.

## 7. CLV and close validity (capture rules)

- CLV = no-vig implied probability of the side at close minus at entry,
  each from a real matched two-sided pair at the **same line**.
- **Close:** the last capture before tipoff and **no more than 60:00
  before** tipoff (exactly 60:00 is valid; at/after tipoff is not a close).
- **Pairing (close):** both sides of a close pair must come from
  captures within a **≤150-second** span; wider is `PAIR_SPAN_EXCEEDED`
  (CLV-missing).
- **Entry pairing (declared, stricter):** the pinned runner
  (`nfl_nba_engine_card_annex.py`, sha256 `28edafba…`) refuses an entry
  pair whose sides are more than **120 seconds** apart
  (`DK_PAIR_CAPTURE_SPAN_EXCEEDED`). Such a row is an **entry refusal**
  (§8): never priced, not a CLV-missing row, and not in the 20% limit.
  This draft does not change the runner.
- **Freshness:** any quote older than **180 seconds** when bound is
  refused (`QUOTE_STALE_180S`).
- Validity checks (timing, two-sidedness, freshness, span) run
  **before** any moved classification; a row with no valid close is a
  capture failure, never a moved row.
- "Final" means final among records committed at review time; later
  commits never rewrite a pairing.

## 8. Missing CLV and fail-closed refusal codes

Exactly one reason per row; excluded from means, never zero-filled.

CLV-missing: `NO_CLOSE_ROW`, `LINE_MOVED` (valid two-sided pre-tip
close exists only at a different line), `CLOSE_SINGLE_SIDED`,
`CLOSE_NOT_PRETIP`, `CLOSE_STALE` (>60:00), `PAIR_SPAN_EXCEEDED`
(>150 s), `QUOTE_STALE_180S`.

**Excluded-and-counted codes (row not scored in the affected legs;
each counted and reported at review):** `RESULT_UNAVAILABLE` (no final
in the settlement source, §3), `VOID` (postponed/suspended/cancelled
game, §3), `PUSH` (final equals the graded line; excluded from 6d),
`GAP_ZERO` (mean equals entry line; excluded from 6c).

**Insufficient-close rule:** per §6, >20% of engine-priced rows without
a valid close gives `INSUFFICIENT_CLOSE_DATA`. Void, push, and
`RESULT_UNAVAILABLE` rows are counted and reported (§3).

Engine/runner refusals (row never priced, counted and reported):
`NBA_TEAM_PERIOD_TEAM_NOT_IN_HISTORY`,
`NBA_TEAM_PERIOD_INSUFFICIENT_TEAM_PRIORS`,
`NBA_TEAM_PERIOD_INSUFFICIENT_LEAGUE_PRIORS`,
`NBA_TEAM_PERIOD_TARGET_INVALID`, `NBA_FIXTURE_IDENTITY_INCOMPLETE`,
`NBA_TEAM_SELECTION_UNBOUND`, `NBA_ENGINE_FAILED:<type>`,
`DK_PAIR_MISSING_OR_STALE`, `TWO_SIDED_OU_REQUIRED`,
`DRAFTKINGS_QUOTE_REQUIRED`, `FINITE_DK_ODDS_REQUIRED`,
`NATIVE_TWO_SIDED_QUOTES_REQUIRED`, `DK_PAIR_CAPTURE_SPAN_EXCEEDED`
(the six pinned-runner entry refusals),
`MARKET_OUT_OF_SCOPE`, `ENTRY_NOT_PRETIP`, `ENTRY_SINGLE_SIDED`,
`PRICE_INVALID`, `ENGINE_PROVENANCE_MISSING`, `HISTORY_HASH_MISMATCH`.
Any code not listed here that appears at review is itself a defect and
blocks the verdict (`UNDECLARED_REFUSAL_CODE`). A malformed row is
refused alone; it never aborts the slate.

## 9. Multiple testing and intervals

- All intervals: **game-cluster bootstrap, 10,000 resamples**, seed fixed
  and recorded at freeze, **two-sided at level 1 − α/k**, α = 0.05.
- **k** = the number of forward clocks whose counting windows overlap
  this test's window, counting this test from its freeze date. The list
  of clock IDs is recorded at freeze and again at review; the larger k
  is used.

## 10. Verdicts

- `BEATS_MARKET` — §6a, §6b, §6c, §6d all hold.
- `DOES_NOT_BEAT_MARKET` — any of them fails. **Per §0, a failure of
  6a is the expected-risk outcome and is recorded as such, not
  explained away.**
- `INSUFFICIENT_CLOSE_DATA` per §8.
A `BEATS_MARKET` verdict does not change registration, eligibility, or
promotability; any change is an owner ruling.

## 11. Version rules

- The engine, runner, history store pins, pick rule, and evaluator
  are fixed by sha256 at the freeze commit. Each slate's run record
  must prove it executed the frozen hashes, or the slate does not count.
- Any change to engine, store discipline, pick rule, or scoring after
  the freeze is a **new version** under a new document, scored only
  from its own freeze forward, never on games the earlier version saw.
- Frozen text is never edited; amendments supersede by reference.
- History refresh: each slate's history snapshot includes only games
  final before the entry capture, and its hash is recorded before pricing;
  a failed refresh fails the slate closed.

## 12. Freeze checklist (owner)

- [ ] Independent re-review of this revision by a checker who did not
      draft it, returning CLEARED; bootstrap seed and the k clock-ID
      list recorded in the freeze record.
- [ ] Owner confirms ±2.0 pick threshold and the team-totals exception to the focus pause, at freeze.
- [ ] Forward evaluator lands, hash-pinned to this document, and is
      independently reviewed, before the first counted slate.
- [ ] Owner freezes; k recorded. The freeze record names the first
      counted slate as **"first slate priced after the evaluator is
      pinned and reviewed"**. No primary metrics (§6) are computed on
      forward rows before then.
