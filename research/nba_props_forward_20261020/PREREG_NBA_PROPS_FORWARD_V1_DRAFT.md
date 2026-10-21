# PREREGISTRATION — NBA Player Props Forward Test V1

# DRAFT — NOT FROZEN, NOT IN FORCE

**This document is a draft. Freezing is the owner's act. No game,
row, or capture counts toward this test until the owner freezes this
document (or a successor) as the governing preregistration, and rows
produced before that freeze are historical record, never prospective
entries. Nothing in this draft changes any family's registration,
eligibility, or validation state.**

- Status: `DRAFT_NOT_IN_FORCE`
- Date drafted: 2026-10-20
- Engine under test: `NBA_PROP_EMPIRICAL_V1`
  (`sportsedge/nba_prop_empirical.py`), priced on cards by
  `sportsedge/nba_phone_prop_pricing.py` through
  `artifacts/run_it_full.py`.
- Construction spec: `nba_props_calibration_spec_v1.md` (Oct 17
  program, sha256
  `47dc1314b608d8a1ae64f869ca8ff48d6add35fcc8ffd2c6ff292d515e1710c2`)
  plus the Oct 18 extension spec `SPEC_NBA_EXTENSION_V1.md` (sha256
  `d5f794bd470f06a7d5094137415e8f210e5c3372fee168d4d0fce27e26822938`)
  for PRA.
- Families in scope (§2): NBA player points, rebounds, assists, PRA
  — registered REGISTERED_RESEARCH_ONLY / NOT_VALIDATED by the
  2026-10-20 "Build the engines" directive; eligible False,
  promotable False. PLAY remains impossible under this test.

## 1. Purpose and scope

The Oct 17/18 calibration programs scored this construction
BEATS_BASELINE on n=16,818 player-games — against league-climatology
baselines only. No market leg exists: the families' readiness
verdict is NO-GO with the exact reason NO_MARKET_TEST, and their only
forward path is a preregistered forward test against our own
timestamped DraftKings captures. This document is that test, for the
four families the capture program covers (Capture Spec V1: NBA game
lines + PTS/REB/AST + common combos).

The question, stated before any data is seen under this document:
do the engine's point-in-time prices beat the contemporaneous
DraftKings market on the rows it picks, measured primarily by
closing-line value against the final pre-tip capture, with
calibration of the model probabilities as the secondary leg?

## 2. Markets in scope

Exactly four, by canonical registry family:

- `player_points` (PTS)
- `player_rebounds` (REB)
- `player_assists` (AST)
- `player_pra` (PRA — points + rebounds + assists, priced from the
  per-game summed distribution, never from an independence
  assumption across the three stats)

**PRA counts only on slates where combo lines were actually
captured** (per Capture Spec V1 and the readiness verdict's note).
A PRA row without a captured two-sided combo quote is not an entry.

Every other NBA family or market — threes, steals, blocks,
turnovers, double-double, team totals, quarters, halves, game
moneyline/spread/total, exotics — is out of scope. An out-of-scope
row reaching an evaluator is refused `MARKET_OUT_OF_SCOPE` and
excluded from inference; it is never silently absorbed into a
denominator.

## 3. Data: our own timestamped DK captures only

Scoring uses exclusively the capture program's committed records
(Capture Spec V1, in effect on main). Every row carries: sport,
league, event/teams/start CT, market, full player name, line, side,
American price, book=DraftKings, `captured_at` ISO with timezone,
ENTRY/CLOSE designation, source page/view, entered_by. No fabricated
or retroactive prices; a partial board is never called full;
two-sided markets record both sides; screenshots are evidence
attached to a row, never a substitute for it.

Model inputs are point-in-time by construction and by store
discipline: the engine prices from game logs strictly before the
target game's calendar date (date granularity), over the
sportsdataverse box-score history the operator supplied, with DNP
(minutes = 0) rows excluded. The engine has **no participation,
minutes-projection, or availability feed** — that limitation is
declared on every priced row and is part of what this test measures
the cost of; it is never repaired inside the test window.

## 4. Slates, rows, and the prospective count

- A slate is one NBA game date's captured board.
- Prospective counting starts at zero and begins with the first
  slate captured **after** this document is frozen by the owner.
  Rows from games on or before the freeze date never count, however
  they were produced.
- No verdict review before **all** of: 4 full slates AND at least
  50 rows AND exactly 40 distinct games **per market** (a market is
  reviewed when its own counters are met; §10). One early look ends
  the test's claim to be preregistered.
- Any market under 100 rows at scoring time stays
  `INSUFFICIENT_SAMPLE` regardless of its point estimate.

## 5. Row construction rules

The evaluator consumes only runner-produced rows for in-scope
fixtures:

- League NBA and family in §2, else excluded.
- `home_team` and `away_team` must both parse.
- Side OVER or UNDER; line numeric; entry price numeric.
- The row must carry the engine stamp: `engine_id` =
  `NBA_PROP_EMPIRICAL_V1`, `sufficiency_met` true, `n_prior` ≥ 10,
  pool source, store provenance, and the engine's declared
  participation limitation. A row without engine provenance is not
  an engine row and is excluded (and reported).
- PICKED: a row the runner surfaced as a research candidate
  (`RESEARCH_CANDIDATE_NOT_VALIDATED`: model probability implies
  EV ≥ the card's shortlist floor against the entry quote). PASSED:
  an engine-priced row that was not picked. Both groups are recorded;
  the verdict needs both (§9).

## 6. CLV: definition (primary metric)

CLV is computed per row against the **final pre-tip capture** of the
same fixture, player, market, and side (the CLOSE record per §7):
the side's **no-vig implied probability at close minus its no-vig
implied probability at entry**, no-vig computed from the real
matched two-sided quote pair at the same line. A close quote-pair
without both sides yields no no-vig probability and the row's CLV is
missing (§8), never estimated. CLV is the primary metric; win/loss
is secondary and is never promoted over CLV by this preregistration
(old-regime CLV-vs-result disagreements are adjudicated by this
document: CLV governs).

## 7. Close-capture validity

- Close time is fixture-local: the last capture of the game before
  tipoff, and **no more than 60 minutes before** tipoff. A capture
  after tipoff is not a close. A close exactly 60:00 before tipoff
  is valid.
- Both sides of the pair must come from the same close capture at
  the entry line; a close showing only the picked side is
  single-sided and yields `CLOSE_SINGLE_SIDED`.
- "Final" means final among committed records at scoring time;
  records committed later never retroactively rewrite a pairing.

## 8. Missing CLV: reason codes

A picked or passed row without a valid close pairing gets exactly
one `CLV_MISSING` reason and is excluded from CLV means (never
zero-filled, never carried at entry price):

- `NO_CLOSE_ROW` — no close capture contains the fixture/player/
  market/side at all.
- `LINE_MOVED` — the close capture carries the row at a different
  line than the entry line.
- `CLOSE_SINGLE_SIDED` — the close capture carries only one side of
  the pair.
- `CLOSE_NOT_PREKICKOFF` — the only candidate close capture is at or
  after tipoff.
- `CLOSE_STALE` — the last pre-tip capture is more than 60 minutes
  before tipoff.

**Insufficient-close rule:** if more than 20% of a market's rows are
`CLV_MISSING`, that market's verdict is `INSUFFICIENT_CLOSE_DATA`
regardless of the CLV point estimate on the remainder.

## 9. Verdict rules (per market)

Per market, at a scheduled scoring that satisfies §4:

- `BEATS_MARKET` — mean CLV on picked rows > 0 with the lower bound
  of the 95% game-clustered confidence interval above 0, **and**
  picked rows' mean CLV exceeds passed rows' mean CLV (the engine
  must beat the contemporaneous market, and its picks must beat its
  own passes — beating neither or only one is not beating the
  market).
- `DOES_NOT_BEAT_MARKET` — the interval includes or lies below 0, or
  the picked-vs-passed ordering fails.
- `INSUFFICIENT_SAMPLE` / `INSUFFICIENT_CLOSE_DATA` per §4/§8.
- Calibration leg (secondary, reported alongside, never a substitute
  verdict): realized over/under/push frequencies vs the engine's
  stated probabilities on all engine-priced rows (picked and
  passed), with game-clustered intervals; settlement uses the
  captured line and official final box scores (sportsdataverse
  results path).

Beating the market under this test is the only route by which a
family's validation state may be proposed for change, and any such
change remains an owner ruling. A `BEATS_MARKET` verdict here does
not by itself make any family eligible or promotable.

## 10. Inference discipline

- Confidence intervals are clustered by game (rows from one game
  are not independent: one blowout moves every prop in it).
- No interim verdicts: family-level results are computed only at a
  scoring that satisfies §4's floors, once, on the records then
  committed.
- Version rule: the engine version is the one named in this
  document's header, as frozen at freeze time. Any change to the engine, the store discipline, or
  this scoring after the freeze is a **new version** scored only
  from that point forward, under a new versioned document — never
  an edit to this text, and never graded on games the earlier
  version was tuned against.
- Amendments are new versioned documents that supersede by
  reference. Frozen text is never edited.

## 11. What this test does not do

- It does not authorize PLAY, staking, or any account action.
- It does not change any family's registration by itself.
- It does not score NBA game markets (moneyline/spread/total remain
  FAILED_VALIDATION-blocked on their own record) or any out-of-scope
  family.
- It does not repair the engine's declared limitation (no
  participation/minutes feed) inside the window; rows are scored as
  the engine priced them.

## 12. Freeze checklist (owner)

- [ ] Owner freezes this document (commit hash recorded here by the
      freezing amendment).
- [ ] Evaluator implementation lands and is hash-pinned to this
      document before the first counted slate is priced.
- [ ] Capture program confirmed live for the four families including
      PRA combos (Capture Spec V1 NBA scope).
- [ ] First counted slate named (the first NBA game date captured
      after the freeze).

*Drafted 2026-10-20 alongside the engine build
(`feat/nba-prop-engines-20261020`). Modeled on the NFL Props Part 2
forward preregistration's discipline; not in force until frozen by
the owner.*
