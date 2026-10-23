# PREREGISTRATION — NBA Team Totals Forward Test V1

# DRAFT — NOT FROZEN — NOT IN FORCE — NO GAMES COUNT

**This document is a draft pending (1) an independent review by a
checker who did not write it and (2) the owner's freeze. No game,
row, or capture counts toward this test until the owner freezes this
document (or a successor). Rows produced before the freeze are
historical record, never prospective entries. Nothing in this draft
changes any family's registration, eligibility, or validation state.**

- Status: `DRAFT_NOT_IN_FORCE` (pending independent review + owner freeze)
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

**Missing-offer games.** When DraftKings offers no team total for a
game (e.g. the 2026-10-22 PM capture: none for 2 of 14 games), the
game is listed per slate in a `MISSING_OFFER` report with the capture
id and timestamp. It is **never backfilled** from another book, a later
capture, a derived game-total split, or any estimate, and it is never
counted in any denominator. The missing-offer count and share are
reported at review alongside the verdict.

## 4. Slates and gates (minimums) and the single review

- A slate is one NBA game date's captured board. Counting starts at
  zero with the first slate priced after the freeze.
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
- Side OVER/UNDER; numeric line; numeric American price; both sides of
  the entry pair captured.
- Engine stamp required: `engine_id = NBA_TEAM_PERIOD_RATINGS_V1`,
  `status = PRICED`, `sufficiency_met = true`, priors recorded. Rows
  without engine provenance are excluded and reported.
- **Pick rule (fixed now):** `gap = mean − entry_line`. PICKED OVER if
  `gap ≥ +2.0` points, PICKED UNDER if `gap ≤ −2.0`; otherwise PASSED.
  One pick per team per game. *(Owner confirm: the engine emits a mean
  only, no distribution; this threshold rule is the drafted choice
  instead of an invented probability model. Changing it after the freeze
  is a new version.)*

## 6. Primary test (both legs required)

**6a. Accuracy vs the market baseline (governing).** On every
engine-priced row with a valid close (§7), paired per row against the
final team points:

- `ΔMAE_mkt = MAE(engine mean) − MAE(DK close line)`
- Required: the upper bound of the (Bonferroni-adjusted, §9)
  game-clustered CI of `ΔMAE_mkt` lies **below 0**. Squared error (RMSE)
  difference is reported alongside with the same CI.

**6b. Accuracy vs the ratings construction's baselines.** Same rows,
same CI: the engine must also beat the emitted naive baselines
`home/away_team_mean` (B1) and `league_mean` (B2) — the baselines its
historical screen beat. Failing this means the construction lost its
own historical edge forward.

**6c. CLV on picks.** Mean CLV on PICKED rows > 0 with the adjusted
CI lower bound above 0, AND picked mean CLV > passed mean CLV.

`BEATS_MARKET` requires 6a AND 6b AND 6c. Calibration-style reporting
(hit rates by gap bucket) is secondary and never substitutes.

## 7. CLV and close validity (capture rules)

- CLV = no-vig implied probability of the side at close minus at entry,
  each from a real matched two-sided pair at the **same line**.
- **Close:** the last capture before tipoff and **no more than 60:00
  before** tipoff (exactly 60:00 is valid; at/after tipoff is not a close).
- **Pairing:** both sides of a pair must come from captures within a
  **≤150-second** span.
- **Freshness:** any quote older than **180 seconds** at the time it is
  bound is refused (`QUOTE_STALE_180S`), never priced or paired.
- Validity checks (timing, two-sidedness, freshness) run **before** any
  line-moved classification; a row with no valid close is a capture
  failure, never a "moved" row.
- "Final" means final among records committed at review time; later
  commits never rewrite a pairing.

## 8. Missing CLV and fail-closed refusal codes

Exactly one reason per row; excluded from means, never zero-filled.

CLV-missing: `NO_CLOSE_ROW`, `LINE_MOVED` (valid two-sided pre-tip
close exists only at a different line), `CLOSE_SINGLE_SIDED`,
`CLOSE_NOT_PRETIP`, `CLOSE_STALE` (>60:00), `PAIR_SPAN_EXCEEDED`
(>150 s), `QUOTE_STALE_180S`.

**Insufficient-close rule:** if >20% of engine-priced rows are
CLV-missing, the verdict is `INSUFFICIENT_CLOSE_DATA`.

Engine/runner refusals (row never priced, counted and reported):
`NBA_TEAM_PERIOD_TEAM_NOT_IN_HISTORY`,
`NBA_TEAM_PERIOD_INSUFFICIENT_TEAM_PRIORS`,
`NBA_TEAM_PERIOD_INSUFFICIENT_LEAGUE_PRIORS`,
`NBA_TEAM_PERIOD_TARGET_INVALID`, `NBA_FIXTURE_IDENTITY_INCOMPLETE`,
`NBA_TEAM_SELECTION_UNBOUND`, `NBA_ENGINE_FAILED:<type>`,
`MARKET_OUT_OF_SCOPE`, `ENTRY_NOT_PRETIP`, `ENTRY_SINGLE_SIDED`,
`PRICE_INVALID`, `ENGINE_PROVENANCE_MISSING`, `HISTORY_HASH_MISMATCH`.
Any code not listed here that appears at review is itself a defect and
blocks the verdict (`UNDECLARED_REFUSAL_CODE`). A malformed row is
refused alone; it never aborts the slate.

## 9. Multiple testing

Bonferroni: every CI in §6 is computed at level `1 − α/k`, α = 0.05,
where **k = the number of active forward clocks at this test's review
date**, counting this test from its freeze date. k is recorded at freeze
and at review; the larger is used. Intervals are clustered by game.

## 10. Verdicts

- `BEATS_MARKET` — §6a, §6b, §6c all hold.
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

- [ ] Independent review by a checker who did not draft this document.
- [ ] Owner confirms §5 pick threshold (±2.0 points).
- [ ] Forward evaluator lands, hash-pinned to this document, before the
      first counted slate.
- [ ] Owner freezes; k recorded; first counted slate named.
- [ ] Owner ruling on the focus pause (2026-10-22) permits this freeze.
