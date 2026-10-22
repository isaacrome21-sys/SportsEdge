# OddsPapi Provenance Admission Protocol

## DRAFT — NOT ADOPTED

**Status: DRAFT — NOT ADOPTED.** This document proposes an admission test for
OddsPapi (oddspapi.io) as a historical-odds source for SportsEdge's
market-baseline validation leg. It has not been run, has not been ruled on by
the owner, and admits nothing. Until every applicable check below passes and
the owner adopts this protocol, **no OddsPapi line counts as evidence for any
SportsEdge purpose.**

Drafted: 2026-10-20. Admission, if granted, is **per sport, per market, per
book** — never global. A pass for NBA moneylines admits NBA moneylines only.

---

## 0. Principles

1. **Provenance before use.** A line whose origin, book, and timestamp
   semantics cannot be demonstrated is a number of unknown vintage. Numbers of
   unknown vintage cannot produce verdicts (standing SportsEdge rule).
2. **Admission is granular.** Each sport × market × book cell is admitted or
   not, on its own checks. Failure in one cell does not contaminate a passing
   cell; a pass in one cell does not launder a failing one.
3. **Missingness is measured, never assumed.** A cell whose coverage was not
   measured is `NO_DATA` — not admitted, not zero, not "probably fine."
4. **Any failed check = NOT ADMITTED for that cell.** No averaging across
   checks, no partial credit, no owner-override inside this protocol (the
   owner may reject this protocol, but may not waive a failed check under it).
5. **Evaluation-side only, forever.** Even if admitted, OddsPapi data is a
   market baseline for historical screens. It is never a pricing input, never
   appears on a card, and never substitutes for a paired DraftKings capture in
   any forward test (see §7).

## 1. Reference corpora (the ground truth the checks compare against)

| ID | Corpus | Location |
|----|--------|----------|
| R1 | Our own paired DraftKings captures, Oct 19–20 2026 (NBA) | Records branch `records/audit-artifacts-20261018`, `records/audit_artifacts_20261018/dk_line_archive/nba/2026-10-19/{1053,1154,1721}_ct.json`, `.../2026-10-20/{0537,1023,1722}_ct.json`. Each game carries spread / moneyline / total / team-totals blocks and player props (points, rebounds, assists, PRA), each market with its own `captured_at` (ISO, −05:00). Capture files were verified clean of numeric contamination on 2026-10-20. |
| R2 | SBR NBA closing-line archive (used in the Oct 18, 2026 NBA totals-bias diagnosis) | `~/workspace/sportsedge/nba_totals_bias_20261018/data/sbr_clone/data/nba_archive_10Y.json` — output of the `flancast90/sportsbookreview-scraper` clone in the same directory; 13,903 game records with `home_close_ml`, `away_close_ml`, `home_open_spread`, `home_close_spread`, `open_over_under`, `close_over_under`, dates and teams. Diagnosis report: `~/workspace/sportsedge/nba_totals_bias_20261018/REPORT.md`. |
| R3 | SBR MLB archive (same clone) | `~/workspace/sportsedge/nba_totals_bias_20261018/data/sbr_clone/data/mlb_archive_10Y.json` |
| R4 | Our own Oct 19, 2026 MLB record — ALCS Game 6, TB @ CLE | `~/workspace/sportsedge/operative_run_20261019_mlb_alcs_g6/` (`CARD.md`, `lines_capture.json`): moneyline TB −158 / CLE +130, run line TB −1.5 (+144), captured pregame by us. |

The candidate data pull from OddsPapi must itself be frozen before checking:
export files saved under this protocol's run directory with sha256 recorded.
Checks run against that frozen pull only — never against a live, mutable API
response re-fetched mid-check.

## 2. Check A — Agreement with our own DraftKings captures (NBA)

The strongest provenance test available: same book (DraftKings), same games,
timestamps known to the minute from our own receipts.

**Sampling.**
- *Targeted set:* every game-line (spread, moneyline, total) pair in R1 files
  `2026-10-20/1023_ct.json` (14 games) and `2026-10-20/1722_ct.json` (13 games)
  — 27 games, 81 (game, market) pairs.
- *Random set:* 40 further (game, market) pairs drawn uniformly from the
  remaining four R1 files, sampling script and seed recorded in the run
  report.
- *Props set (separate cell):* 60 (player, market) pairs drawn uniformly from
  the points/rebounds/assists/PRA rows of the 1023 and 1722 files, seed
  recorded.

**Comparison, per pair.** Take the OddsPapi DraftKings quote for the same
game and market whose timestamp is nearest to our market-level `captured_at`.
All three must hold:

1. **Time:** |OddsPapi timestamp − our `captured_at`| ≤ 30 minutes.
2. **Line:** spread/total line exactly equal (lines move in 0.5 steps; a
   half-point difference is a different quote, not a rounding difference).
   Moneyline has no line component.
3. **Price:** American price within ±10 points of ours on the matched side
   (juice moves faster than lines; ±10 is the tolerance, not a target).

**Pass bar (per cell — game lines, and props separately):**
- ≥ 95% of sampled pairs satisfy all three conditions, **and**
- 100% of matched OddsPapi timestamps fall inside the ±30-minute window
  (a quote that cannot be time-located near a known receipt is not a
  near-miss; it is unverifiable), **and**
- zero matched quotes whose OddsPapi timestamp is after the game's recorded
  start while being presented as a pre-game quote (any such case is also an
  automatic Check D failure).

## 3. Check B — Closing-line agreement with the SBR archive (NBA)

Tests whether OddsPapi's "closing" lines are the closes the market actually
printed, against an independent archive SportsEdge already used for the
Oct 18 totals-bias diagnosis (R2).

**Sampling.** Stratified random sample of ≥ 200 games from R2 spanning ≥ 4
distinct seasons, plus a targeted set: every R2 game from the final week of
the most recent complete season in the archive. Script and seed recorded.

**Comparison, per game.** OddsPapi's closing quote for the book it claims
(moneyline, spread, total) vs R2's `home_close_ml` / `away_close_ml`,
`home_close_spread`, `close_over_under`. Book identity must be explicit in
the OddsPapi pull; if the book for a "close" cannot be identified, that game
is scored as a failure, not skipped (unidentifiable book = unverifiable
provenance).

**Pass bar (per market):**
- Moneyline: price within ±10 American points on ≥ 97% of sampled games.
- Spread and total: line exactly equal on ≥ 95%; |Δline| ≤ 0.5 on ≥ 99%;
  **no** sampled game with |Δline| > 1.0.
- No sampled game missing a closing quote in the OddsPapi pull for a market
  the cell claims to cover (missingness feeds Check E, and also counts
  against these percentages — denominators are sampled games, not returned
  games).

## 4. Check C — MLB agreement (ALCS record + SBR MLB archive)

**C1, targeted.** R4 is the only MLB game in our own Oct 19–20 records, so it
is a necessary-but-not-sufficient check: OddsPapi's DraftKings quote for
2026-10-19 TB @ CLE must reproduce moneyline TB −158 / CLE +130 within ±10
points per side and run line TB −1.5 exactly, from a quote timestamped
before first pitch. Any miss fails the MLB moneyline and run-line cells
outright (n = 1 by necessity; the check is cheap and the record is ours).

**C2, historical.** Stratified random sample of ≥ 200 games from R3 spanning
≥ 4 seasons, compared against OddsPapi closing moneylines (and run
lines/totals where the archive carries them), under the same numeric bars
as Check B. Script and seed recorded.

## 5. Check D — Timestamp semantics

OddsPapi's timestamps must demonstrably mean what a validation baseline
needs them to mean: the time the quoted price was in effect (quote time),
not the time of scrape, ingest, or database write. Tested, not asserted:

1. **Closes precede starts — 100%, no tolerance.** For every sampled quote in
   Checks A–C labeled closing/final, the OddsPapi timestamp is strictly
   before the event's start time. One violation fails this check.
2. **Closes are actually closes.** For ≥ 95% of sampled closing quotes, the
   timestamp falls in [start − 6h, start). A systematic pattern of "closes"
   stamped many hours early is a stale open wearing a close's label.
3. **Offset identifiability.** Using the ≥ 10 Check A pairs with the smallest
   |Δt|, infer OddsPapi's timezone basis (UTC vs local vs other). The implied
   offset must be a single consistent value across all 10. Inconsistent
   offsets = timestamps are not quote times in any stable frame = fail.
4. **No impossible quotes.** In a full quote history pulled for ≥ 50 games
   across admitted-candidate cells: no timestamp after retrieval time, no
   pre-game quote timestamped after start, and each game's quote series is
   non-decreasing in its own stated update order. Any violation fails.

## 6. Check E — Coverage accounting

For each sport × market × book cell OddsPapi claims to cover, over each
sampled window used above (and, for admission, at minimum the windows of
Checks A–C):

- **Denominator:** games actually played in the window (from R1/R2/R3/R4 or
  the official schedule record used in that check).
- **Numerator:** those games with ≥ 1 usable OddsPapi quote for the cell
  (right game, right market, parseable line and price, timestamp present).
- **Coverage = numerator / denominator, printed in a matrix in the run
  report.** Admission requires coverage ≥ 90% in every sampled window for
  that cell.
- A cell not sampled is **NO_DATA**: not admitted, not failed — unmeasured.
  The matrix must list NO_DATA cells explicitly; silence about a cell is a
  defect in the run report, not a pass.
- Silent omissions count: if OddsPapi's own catalog claims a game the pull
  then lacks, the game stays in the denominator.

## 7. Standing limits if a cell is admitted

1. **Evaluation-side only.** Admitted OddsPapi lines may serve solely as the
   market baseline in historical validation screens. They are never a
   pricing input to any model, never enter `run_it_full.py` or any card,
   and are never blended with SportsEdge numbers.
2. **SCREEN labeling.** Every result computed against an OddsPapi baseline is
   labeled `SCREEN` with the source named (book, pull date, pull sha256).
   A screen is not a verdict and cannot promote, validate, or price
   anything.
3. **Frozen forward tests are untouchable.** OddsPapi data does not alter
   the terms, inputs, or verdicts of any frozen forward test (NBA props
   forward V1, NFL props Part 2 / 2B, NFL anytime-TD V1, and successors).
   In particular, an OddsPapi "close" never substitutes for a missing
   forward-test close: a row that is `CLV_MISSING` under a frozen prereg
   stays `CLV_MISSING`.
4. **No retroactive verdicts.** Historical screens on OddsPapi baselines are
   version-scored like everything else: they describe the model version as
   it stood, and never rewrite a frozen forward verdict, a recorded refusal,
   or a settled card.
5. **Admission expires.** Any OddsPapi API, schema, or book-coverage change,
   or 12 months elapsing, voids admission for affected cells until the
   applicable checks re-pass on a fresh frozen pull.

## 8. Run report requirements

An admission run is complete only when its report records: the frozen pull's
file list and sha256s; sampling scripts and seeds; per-check sample sizes,
failure counts, and the failing examples verbatim; the Check E coverage
matrix including NO_DATA cells; and the resulting per-cell disposition
(ADMITTED / NOT ADMITTED / NO_DATA). Dispositions take effect on the
report itself: under the owner's delegation and Rocky's market-baseline
ruling of Oct 20, 2026, admission is AUTOMATIC UPON PROOF — a cell that
passes every applicable check stands ADMITTED when the run report is
filed, with no further ruling required; the report is delivered to the
owner as the record of the decision, not as a request for one.

---

*DRAFT — NOT ADOPTED. Workspace record only; not a repo document, not a
preregistration, not a ruling.*
