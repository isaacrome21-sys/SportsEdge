# PREREGISTRATION (DRAFT) — NFL quarter / first-half lines: forward test vs captured DraftKings prices

**Status: DRAFT — NOT FROZEN, NOT IN FORCE, AND NOT FREEZABLE in this
pack.** The family's first construction (`NFL_PERIOD_SHARE_V1`)
failed its design screen (`SCREEN_REPORT.md`); per program law it
does not advance, and no construction may be frozen under this draft
until a successor construction passes its own pre-committed design
screen and is named in a revision of this draft. These terms are
written now — before any forward period-line data exists under them —
so the eventual freeze is a decision about a construction, not about
terms fitted to outcomes. **Freezing is the owner's act. No game, row,
or slate counts toward this test before its freeze.**

Framework config: `sportsedge/forward_validation/configs/nfl_period_lines.json`.
At freeze, this document and that config freeze together; the config
carries `model_version: "UNPINNED"` (a sentinel no row can match, so every row is refused fail-closed) until a construction is named, and the
framework refuses rows for an undeclared version.

Structure: the frozen NFL props Part 2 test
(`research/nfl_props_part2_20261018/PREREG_NFL_PROPS_PART2_FORWARD_V1.md`),
whose capture, close, and missing-close rules this draft adopts
verbatim in effect. Verdicts issue **per market, never pooled** (the
Part 2 rule) — Q1 total and Q3 spread are different markets with
different verdicts.

## 1. Markets in scope

Quarter markets, each two-sided at DK's main line: `TOTAL_1Q`,
`SPREAD_1Q`, `ML_1Q`, `TEAM_TOTAL_1Q`, and identically for 2Q, 3Q, 4Q;
first-half markets: `TOTAL_1H`, `SPREAD_1H`, `ML_1H`, `TEAM_TOTAL_1H`.
Second-half markets are **out of scope** (in-play prices; assigned to
the live family — see the design doc). Settlement is regulation
period scoring only: a quarter market settles on that quarter's
points; 1H on Q1+Q2; overtime never enters any market in this family.
Line storage follows the framework convention (`line` on the
realized-value scale for the over side; a home quarter spread stored
on the home-margin scale with over_side HOME).

## 2. The construction bound (to be named at revision)

The frozen revision of this draft names the construction, its
`model_version`, and its sha256 pins, and records its design-screen
result against criteria fixed before that screen ran. The
construction must produce, per team-game, a joint distribution over
the four quarters' points for both teams (period markets are
two-team objects: a quarter total is a sum, a quarter spread a
difference), from point-in-time inputs only (games final before the
entry capture; the slate's history snapshot hashed before pricing; a
failed refresh fails the slate closed). It takes no market input.

## 3. Universe, captures, pricing

- **Universe:** every paired DraftKings main period line (§1
  markets) for every game on each NFL slate, captured BEFORE kickoff
  — both sides of the same line from the same capture, timestamp
  recorded. **Capture expansion is a precondition of this test:**
  period lines move from issue-comment material to the priced
  per-game capture subset (entry and close) and the NFL intake
  grammar gains period line forms; until both land, this test cannot
  open and no rows exist under it. The expansion is lane work, named
  in the design doc, and does not alter any frozen family's capture
  subset.
- **Entry:** the first DK capture designated ENTRY for the game at
  the main period line. One row per (game, market, team where the
  market is a team market).
- **Committed per-row record** (before kickoff, create-only): game,
  market, team (where applicable), line, both prices + capture
  timestamp, the construction's period distribution summary (mean
  and both-side probabilities), the emitted baseline references (§6b),
  pick classification (§5), entry no-vig probabilities, and the
  sha256 set (this document, engine, history snapshot).
- **Closing capture:** the final pre-kickoff capture, under §7's
  readability rule — for period markets exactly as for full-game
  markets: the close is a **pre-kickoff** object. (A Q1 line trades
  in-play after kickoff; this test never reads an in-play price. Its
  baseline is the last pre-kickoff quote, which is the price the
  market set with the same information the construction had.)

## 4. Slates and gates (minimums) and the single review

Per market (never pooled): **≥100 graded rows AND ≥40 distinct games
AND ≥4 full slates** priced under the frozen package (a slate counts
only if its pricing run covered that game day's full DK period
board). Justification: the 100-row / 40-game floors are the Part 2
verdict floors for a single market (with §4.4's INSUFFICIENT_SAMPLE
rule below 100 rows), adopted because a period market's rows accrue
at the same per-game rate as a Part 2 prop market's — one row per
game per market — and its rows share game scripts the same way.
Markets that never reach their floors report INSUFFICIENT_SAMPLE; the
program does not lower a floor to manufacture a verdict.

**The verdict review for each market happens once, at the first
slate close where that market's gates are met** (the program's
anti-peeking rule); rows beyond the minimums at that close are
included. No interim looks at primary metrics.

## 5. Pick rule (fixed at freeze)

For totals and team totals: gap = model mean − entry line; PICKED at
|gap| ≥ 1.5 points for quarter markets and ≥ 2.0 for 1H markets.
Justification: quarter scoring σ ≈ 5.5–6 points and 1H σ ≈ 8 (from
the activation screen's period panel, 2023–2025), so both thresholds
are ≈ 0.25σ — the same relative stringency class as the sibling
families' pick rules. For spreads: gap on the home-margin scale,
same thresholds. For moneylines: PICKED when the model's win
probability exceeds the entry no-vig probability by ≥ 0.04. Changing
any threshold after the freeze is a new version.

## 6. Primary test (per market; all legs required)

- **6a. CLV (primary).** Mean CLV (no-vig probability points, close
  minus entry, on the model-selected side per the construction's
  probabilities; every priced row is scored on its model-favored
  side, ties recorded TIE and excluded from the denominator, per
  Part 2) over rows with a readable close. Required: the
  game-clustered 95% interval at the §9 level lies **entirely above
  0**.
- **6b. Accuracy vs the existing model.** On the same rows: the
  construction's period means must beat, on MAE against realized
  period scoring, the Lane A surface as it stands at freeze —
  `sportsedge/team_half_pricing.py`'s derivatives for 1H markets
  (its TOTAL_1H / SPREAD_1H / TEAM_TOTAL_1H outputs are UNFITTED
  0.50-scale research pricers; beating them is necessary, not
  sufficient) and, for quarter markets, the league-share decomposition
  B0 of the design screen (no Lane A quarter-total pricer is live —
  the one that existed failed its harness and is retired; the draft
  names B0 as the standing baseline rather than pretend a retired
  construction is the incumbent). Required: upper bound of the §9
  interval for ΔMAE below 0.
- **6c. Calibration.** Model probabilities by decile including the
  extreme decile, reported with every readout; a market whose top
  decile states ≥ 0.80 and realizes ≤ 0.60 at the verdict review is
  DOES_NOT_BEAT_MARKET on calibration grounds regardless of §6a
  (the overconfidence check the Part 2 readout carries, given teeth
  here because period markets invite extreme stated probabilities on
  short samples — stated in advance, not invented at review).

**Moved-row and missing-close rules** are the frozen Part 2 rules
(§4.5 of that test) and the NFL props v1.1 moved-row rules, adopted
verbatim in effect: a readable close is the same game/market/team/
line, both prices, captured before kickoff and no more than 60
minutes before it; every unreadable close is `CLV_MISSING` with
exactly one reason (`NO_CLOSE_ROW`, `LINE_MOVED`,
`CLOSE_SINGLE_SIDED`, `CLOSE_NOT_PREKICKOFF`, `CLOSE_STALE`);
>20% CLV_MISSING in a market → that market's verdict is
`INSUFFICIENT_CLOSE_DATA`; moved picked rows face the one-sided sign
test at α/k and the >50% moved share cap, as in the sibling drafts.

## 7. Verdicts

Per market: `BEATS_MARKET` iff §6a AND §6b AND §6c all hold;
otherwise `DOES_NOT_BEAT_MARKET`; `INSUFFICIENT_SAMPLE` /
`INSUFFICIENT_CLOSE_DATA` per §4/§6. A BEATS_MARKET verdict is the
market's pass under the Oct 27, 2026 validation law; it changes no
registration or eligibility by itself, and PLAY faces the program's
α = 0.05/k accounting. A failed verdict is a result, not a defect to
be tuned away: the construction may return only as a new version
under a new preregistration, scored from its own freeze forward.

## 8. Multiple testing and intervals

Game-cluster bootstrap, 10,000 resamples, seed fixed and recorded at
freeze, intervals two-sided at level 1 − α/k, α = 0.05, k = the
number of families validated or under active forward test in the
program at verdict time (recorded at freeze and at review; the
larger k governs). Verdicts are per market; the family's k accounting
counts the family once, not once per market (the anti-peeking
one-review rule is what disciplines the per-market multiplicity, and
it is stated here so the choice is auditable).

## 9. Integrity bindings

Document, config, engine, and inputs committed before the first row
is priced under the frozen test; captures paired, timestamped,
pre-kickoff; no retrospective additions; closes never backfilled;
historical rows (everything priced before the freeze) graded as
history where graded at all and never counted. Role/injury news is
recorded as context; the construction consumes none of it unless its
own committed design says so.

## 10. Freeze checklist (owner) — all items open

- [ ] Capture expansion landed (period board in the priced subset,
      entry + close) and intake grammar extended, with parser tests.
- [ ] A successor construction named, screened under pre-committed
      criteria, and recorded in a revision of this draft.
- [ ] Independent review (CLEARED) of the frozen revision.
- [ ] Bootstrap seed and §8 k list recorded; freeze by owner ruling
      naming the first counted slate.

*Draft prepared Oct 27–28, 2026 (activation pack). Not frozen; not
freezable until §10's construction item closes.*
