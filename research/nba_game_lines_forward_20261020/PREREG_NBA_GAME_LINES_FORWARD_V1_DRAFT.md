# PREREGISTRATION — NBA Game Lines Forward Test V1

# DRAFT — NOT FROZEN — NOT IN FORCE — NO GAMES COUNT

**This document is a draft. Freezing is the owner's act. No game,
row, or capture counts toward this test until the owner freezes this
document (or a successor) as the governing preregistration, AND the
candidate construction (§3) has passed the historical-screen entry
precondition (§4). Rows produced before both of those events are
historical record, never prospective entries. Nothing in this draft
changes any family's registration, eligibility, or validation
state — in particular, the three families in scope remain
FAILED_VALIDATION on their existing record until a completed
verdict under a frozen successor of this document says otherwise,
and any state change on a verdict remains an owner ruling.**

- Status: `DRAFT_NOT_IN_FORCE`
- Date drafted: 2026-10-20
- Families in scope (§2): NBA moneyline, spread, game total —
  current recorded state FAILED_VALIDATION (accuracy gap first,
  all three markets; §1).
- Candidate under test: **not yet named.** No construction is
  assumed to be the candidate — least of all the incumbent ratings
  model, whose existing record would fail the §4 screen. A
  candidate earns entry only through §3–§4.

## 1. Purpose, and the honest starting state

These three families are not untested; they are tested and failed.
The record, from the Oct 18–19 measurement program (tested-ideas
ledger §§9–10; moneyline record preserved on branch
`records/nba-moneyline-record-20261019` @ `7b72385be`):

- **Moneyline:** paired Brier difference (model − market)
  **+0.0116638, 95% CI [+0.008653, +0.014651]**, n = 4,374 games,
  666 date clusters, 2022-23 → 2025-26, on the pinned ratings model
  (`sportsedge/sports/nba/ratings_model.py` committed defaults,
  sha256 `16e3304718703bcf4ba901fd9bb97b4712d3994d1314f93d93dc19e4bd63ad20`).
  The interval excludes zero on the wrong side: the model is
  measurably less accurate than the market price.
- **Spread:** RMSE model 13.83 vs line 13.30.
- **Game total:** RMSE model 21.46 vs line 20.72.

One caveat is part of the record and is stated here so it is never
lost: the moneyline prices behind that measurement came from a
database with **no timestamps** — closing versus opening is not
established, so the measurement is an **accuracy gap**, not a
beat-the-close verdict. That is exactly the gap this forward test
exists to close: it produces the first verdict for these families
against contemporaneous, timestamped closing prices — our own.

The question, stated before any candidate is named and before any
data is seen under this document: can a candidate construction for
NBA moneyline, spread, and game total — one that has first shown,
historically, accuracy no worse than the market's within a stated
tolerance — beat the contemporaneous DraftKings closing market
going forward, measured primarily by closing-line value against
the final pre-tip capture?

Drafting this document now, before any candidate exists, is
deliberate: the test's terms are written while there is nothing to
protect, so no term can be shaped by a candidate's results.

## 2. Markets in scope

Exactly three, by canonical registry family (NBA):

- `MONEYLINE` — game moneyline, two-sided (home / away)
- `SPREAD` — game spread, two-sided at a single line
- `TOTAL` — game total, two-sided (over / under) at a single line

Every other NBA family — team totals, quarters, halves, player
props of any kind, alternate ladders, exotics — is out of scope of
this document (player PTS/REB/AST/PRA have their own draft
preregistration, `research/nba_props_forward_20261020/`). An
out-of-scope row reaching an evaluator is refused
`MARKET_OUT_OF_SCOPE` and excluded from inference; it is never
silently absorbed into a denominator.

## 3. The candidate: definition

A candidate is a single, fully pinned construction:

- Named module(s) and construction spec, identified by git blob /
  sha256 at the moment of its §4 screen, recorded in the screen's
  own preregistered document.
- One version string, frozen for the life of its clock (§11). The
  incumbent ratings model, any successor model, a challenger, or a
  repaired construction are all equally eligible to be proposed —
  and none is eligible until it passes §4.
- The candidate must produce, per game and per market in §2, from
  point-in-time inputs only (no information timestamped at or after
  tipoff of the game being priced): a win probability (moneyline),
  a margin distribution or implied cover probabilities at the
  captured line (spread), and a total distribution or implied
  over/under probabilities at the captured line (total). A
  construction that cannot state probabilities for a market is not
  a candidate for that market; candidacy is per market, and a
  market without a passing candidate simply has no clock.

## 4. Entry precondition: the historical accuracy screen

No forward clock starts on a construction that has not first faced
history. The screen is itself preregistered — its own versioned
document, written and committed **before** the screen is run —
declaring: the candidate's exact pin (§3); the historical dataset
(source, provenance, and price vintage stated — lines of unknown
vintage cannot support a screen pass, only an accuracy-gap
reading); the seasons and game set; and the tuning disclosure:
which data the candidate was developed or tuned on. **Screen data
that overlaps the candidate's tuning data invalidates the screen.**
A screen is scored **once** per candidate version; a failed
candidate is not re-screened on the same data after adjustments —
an adjusted construction is a new version (§11) requiring its own
screen on data it was not tuned against.

**Pass bar (DRAFT values, owner may amend at freeze):** per market,
paired against the contemporaneous closing line over the same
games, with date/game-clustered 95% confidence intervals:

- **Moneyline:** Brier difference (candidate − market) with the
  interval's upper bound ≤ **+0.002**.
- **Spread:** RMSE difference (candidate − line) with the
  interval's upper bound ≤ **+0.25 points**.
- **Total:** RMSE difference (candidate − line) with the
  interval's upper bound ≤ **+0.25 points**.

"No worse than the market within tolerance" is the whole claim a
screen pass makes. It is an entry ticket, never a validation: the
only verdict instrument is the forward test of §5–§10.

For the avoidance of doubt: the incumbent ratings model, on its
§1 record, **does not meet this precondition** (its moneyline
interval lies entirely above +0.0087, and its spread/total RMSEs
sit above the line's before any interval is consulted). It is
named here not as the candidate but as the reason the precondition
exists.

## 5. Data: our own timestamped DK captures only

Scoring uses exclusively the capture program's committed records
(Capture Spec V1, in effect on main — NBA scope expressly includes
game lines). Every row carries: sport, league, event (teams +
start time CT), market, line where applicable, side, American
price, book = DraftKings, `captured_at` ISO with timezone, ENTRY /
CLOSE designation, source page/view, entered_by. No fabricated or
retroactive prices; a partial board is never called full;
two-sided markets record both sides at both entry and close;
screenshots are evidence attached to a row, never a substitute
for it. Each capture is committed to a records branch as it is
taken.

Model inputs are point-in-time by construction: the candidate
prices from information available before tipoff only, under its
own pinned spec. Any input limitation the candidate carries (a
missing feed, a stale factor) is declared in its §3 record and is
part of what this test measures the cost of; it is never repaired
inside the test window.

## 6. Slates, rows, and the prospective count

- A slate is one NBA game date's captured board.
- Prospective counting starts at zero and begins with the first
  slate captured **after both** the owner freeze of this document
  **and** the candidate's §4 screen pass are committed. Rows from
  games on or before the later of those two events never count,
  however they were produced.
- One priced row per game per market: the candidate's stated
  probabilities for that game and market, the entry quote pair,
  and the model-selected side — the side whose stated probability
  most exceeds the entry no-vig probability. An exact tie is
  recorded `TIE` and excluded. PICKED: a row surfaced as a
  research candidate (model edge at or above the card's shortlist
  floor against the entry quote). PASSED: a priced row that was
  not picked. Both groups are recorded; the verdict needs both
  (§9).
- No verdict review before **all** of, per market (DRAFT values,
  in the program's game-line family pattern): **4 full slates AND
  at least 100 rows AND at least 40 distinct games.** Because each
  game contributes exactly one row per market, the 100-row floor
  is in practice a 100-game floor. One early look ends the test's
  claim to be preregistered.
- Any market under 100 rows at scoring time stays
  `INSUFFICIENT_SAMPLE` regardless of its point estimate.

## 7. CLV: definition (primary metric)

CLV is computed per row against the **final pre-tip capture** of
the same fixture, market, and side (the CLOSE record per §8): the
selected side's **no-vig implied probability at close minus its
no-vig implied probability at entry**, no-vig computed from the
real matched two-sided quote pair at the same line (for spread
and total: the same line; a close at a different line is
`LINE_MOVED`, §8 — it is never re-based). A close quote-pair
without both sides yields no no-vig probability and the row's CLV
is missing (§8), never estimated. CLV is the primary metric;
win/loss and probability quality (§9) are secondary and are never
promoted over CLV by this preregistration.

## 8. Close-capture validity and missing CLV

- Close time is fixture-local: the last capture of the game before
  tipoff, and **no more than 60 minutes before** tipoff. A capture
  after tipoff is not a close. A close exactly 60:00 before
  tipoff is valid; 60:01 is stale.
- Both sides of the pair must come from the same close capture at
  the entry line; a close showing only the selected side is
  single-sided and yields `CLOSE_SINGLE_SIDED`.
- "Final" means final among committed records at scoring time;
  records committed later never retroactively rewrite a pairing.

A picked or passed row without a valid close pairing gets exactly
one `CLV_MISSING` reason and is excluded from CLV means (never
zero-filled, never carried at entry price):

- `NO_CLOSE_ROW` — no close capture contains the fixture/market/
  side at all.
- `LINE_MOVED` — the close capture carries the market at a
  different line than the entry line (spread/total), or, for
  moneyline, carries no matched pair at close.
- `CLOSE_SINGLE_SIDED` — the close capture carries only one side
  of the pair.
- `CLOSE_NOT_PREKICKOFF` — the only candidate close capture is at
  or after tipoff.
- `CLOSE_STALE` — the last pre-tip capture is more than 60 minutes
  before tipoff.

**Insufficient-close rule:** if more than 20% of a market's rows
are `CLV_MISSING`, that market's verdict is
`INSUFFICIENT_CLOSE_DATA` regardless of the CLV point estimate on
the remainder. (Strictly more than 20%; exactly 20% is not
insufficient.)

## 9. Secondary legs (reported alongside, never substitute verdicts)

- **Win/loss:** the model-selected side graded against the
  captured line and the official final score. Spread and total
  pushes are graded rows, excluded from the win/loss denominator;
  moneyline has no pushes. Settlement source: the official final
  (sportsdataverse results path), never a live or projected score.
- **Probability quality vs the close:** paired per game — the
  candidate's stated probabilities scored by Brier and log loss
  against outcomes, against the closing no-vig probabilities
  scored identically on the same games; differences reported with
  game-clustered intervals. This leg answers the §1 caveat
  directly: it is the accuracy comparison, rerun on timestamped
  closing prices. A favorable probability-quality leg does not
  rescue a failed CLV verdict, and an unfavorable one does not
  overturn a passed CLV verdict; disagreements are reported, not
  adjudicated after the fact.

## 10. Verdict rules (per market)

Verdicts are restricted to exactly four values. Per market, at a
scheduled scoring that satisfies §6:

- `BEATS_MARKET` — mean CLV on picked rows > 0 with the lower
  bound of the 95% game-clustered confidence interval above 0,
  **and** picked rows' mean CLV exceeds passed rows' mean CLV
  (the candidate must beat the contemporaneous market, and its
  picks must beat its own passes — beating neither or only one is
  not beating the market).
- `DOES_NOT_BEAT_MARKET` — the interval includes or lies below 0,
  or the picked-vs-passed ordering fails.
- `INSUFFICIENT_SAMPLE` — per §6.
- `INSUFFICIENT_CLOSE_DATA` — per §8.

Beating the market under this test is the only route by which a
family's FAILED_VALIDATION state may be *proposed* for change, and
any such change remains an owner ruling. A `BEATS_MARKET` verdict
here does not by itself make any family eligible or promotable,
and does not authorize PLAY.

## 11. Inference discipline and the version rule

- Confidence intervals are clustered by game (a game's three
  markets are scored per market, but games — not rows — are the
  independent units; dates are the clustering unit where the
  paired-accuracy legs require it, as in the §1 record).
- No interim verdicts: market-level results are computed only at a
  scoring that satisfies §6's floors, once, on the records then
  committed.
- **Version-scoring rule:** every model version is scored **as it
  stood** when it priced the games. The candidate version is the
  one pinned in its §3 record at its §4 screen. Any change to the
  candidate, its inputs, or this scoring after the clock starts
  is a **new version** — scored only from that point forward,
  under a new versioned document and a new screen — never an edit
  to this text, and never graded on games the earlier version was
  already tuned against.
- Amendments are new versioned documents that supersede by
  reference. Frozen text is never edited.

## 12. What this test does not do

- It does not authorize PLAY, staking, or any account action.
- It does not change any family's registration or validation state
  by itself; the three families remain FAILED_VALIDATION until a
  completed verdict and an owner ruling say otherwise.
- It does not count any game captured before the freeze + screen
  (§6), and it does not score any other NBA family (§2).
- It does not promise a candidate will ever exist: if no
  construction passes §4, these families stay FAILED_VALIDATION
  with no clock running, and that outcome — not a lowered bar —
  is the correct state of the record.

## 13. Freeze checklist (owner)

- [ ] Owner freezes this document (commit hash recorded here by
      the freezing amendment).
- [ ] Candidate named and pinned per §3, with its tuning
      disclosure.
- [ ] Candidate's §4 screen preregistration committed, screen run
      once, result committed — PASS per market claimed.
- [ ] Evaluator implementation lands and is hash-pinned to this
      document before the first counted slate is priced.
- [ ] Capture program confirmed live for NBA game lines, entry +
      close (Capture Spec V1).
- [ ] First counted slate named (the first NBA game date captured
      after both the freeze and the screen pass).

*Drafted 2026-10-20 under the owner's "everything running like the
pros / finish everything" directive, so the instrument is ready the
moment a candidate earns entry. Modeled on the NBA props forward
draft (`research/nba_props_forward_20261020/`) and the frozen NFL
Part 2 mechanics (five CLV_MISSING reasons, the >20% rule,
game-clustered inference); not in force until frozen by the owner.*
