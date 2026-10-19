# SportsEdge Board Package V1 — "Build like MySpariEdge"

One file: (1) board product spec, (2) prototype slate board rendered from the real Oct 18, 2026 DraftKings capture, (3) phased build order, (4) appendix — the MySpariEdge methodology audit (Rocky, Oct 18, 2026; builder-authored, research context only) that the spec's "not copied" list is drawn from.

---

# PART 1 — BOARD PRODUCT SPEC

# SportsEdge Slate Boards — Product Spec V1 (DRAFT for owner review)

**Directive:** Isaac, Oct 19, 2026 — "Build like myspariedge."
**What that means here:** adopt MySpariEdge's *product shape* — daily per-sport slate
boards, per-game boards, a player-prop edge board, ranked best bets, parlay/SGP tooling,
and a public results tracker — rebuilt entirely on SportsEdge discipline. Nothing about
MySpariEdge's math, labels, or presentation shortcuts is adopted (see §7, the explicit
not-copied list).

**Status:** DRAFT SPEC. No code exists yet; build order is in `BUILD_ORDER.md`; a
rendered prototype from real captured data is in `prototype_board.md`.
**Research-only.** SportsEdge has **zero validated families**. Nothing this product
shows is a validated play, and no view may present a row as one.

---

## 1. The one rule everything else hangs from

Every number on every board comes from exactly two places:

1. **Prices:** our own timestamped DraftKings captures (the DK line archive and
   committed capture records). No external odds feed, no scraped consensus, no
   "market average." A price without a capture timestamp does not exist on a board.
2. **Projections:** existing SportsEdge engines, at the version that priced the game,
   named on the row. No blended external projections (MySpariEdge, Covers, Action,
   Stokastic numbers may appear only as separately-labeled research context in a
   card's info pack — never as a board row, never averaged into our numbers).

If either input is missing for a row, the row still renders — labeled **BLOCKED**
with the exact reason. Boards show the full slate, including what we cannot price.
A board that only shows the rows we like is marketing, not a research product.

## 2. Pages / views

### 2.1 Slate board (per sport, per day) — the home view
One row per **game**, columns: matchup, start time (CT), DK ML / spread / total
(both sides, both prices), model projected score (home–away), model projected total,
model projected margin, the game's single best row (by the ranking rule in §2.4)
with its label, and capture time. Games sort by start time; started games move to a
"live/final" section and freeze at their last pregame capture (never re-read
in-game prices into a pregame row).

Per-sport boards at launch scope:
- **NBA** — ML / spread / total / team totals; props in §2.3 scope. NBA total
  rows priced from the RAW construction must carry the explicit named reason
  `WATCH_NBA_TOTAL_RAW_MODEL` (held-out market leg worse than the close;
  the construction's totals add no measured accuracy beyond the line) —
  never a generic WATCH tag.
- **NFL** — ML / spread / total; props per the registered families with engines.
- **MLB** — ML / run line / total; F5 and prop sections per registered families.
- **CFB** — renders **BLOCKED at the registry gate** (`FAMILY_REGISTRY_NOT_VALIDATED`)
  until the owner rules otherwise; the board shows the fixtures and the reason, no prices
  from us, no model numbers.
- NHL / UFC / PGA: **parked** — no boards.

### 2.2 Game board (per game)
The full captured board for one game, grouped by section exactly as captured
(main lines, alternates, team totals, periods, player props, TD scorers, SGP
availability), with each section's capture timestamp. Sections the capture recorded
as **UNREADABLE** render as UNREADABLE with the capture note — never filled, never
dropped silently. Line-move display: where two timestamped reads of the same line
exist (entry vs refresh vs close), the game board shows the sequence with times;
the earliest read is never overwritten.

### 2.3 Prop edge board (per sport, per day)
One row per **player prop selection** that an engine priced (see row schema §3):
player (full name; nflverse `player_id` where the family requires it), game, market,
line, side, DK price, model projection (the stat mean μ), model probability for the
side, edge %, label + reason. Filters: market, minimum edge, team. Sort default:
edge % descending — **with the family's validation banner pinned above the table**
(e.g. "NFL props: CALIBRATED_CANDIDATE — calibration only; verdict comes from the
Part 2 forward test vs captured DK closes. These are unvalidated estimates.").
Rows an engine refused render on a companion "unpriced" list with the refusal
reason (`INSUFFICIENT_GAMES`, `NAME_UNRESOLVED`, `NO_ENGINE`, …) — refusals are
part of the product, not an embarrassment to hide.

### 2.4 Ranked best bets (per sport, per day)
At most one row per market per game (the composite rule: one side per market).
Ranking key: estimated EV of the row's label-eligible set, descending.

- **PLAY section:** exists in the layout from day one and renders **EMPTY** with
  the standing line: *"No validated families — PLAY is unavailable."* It fills only
  when a family validates under a frozen forward protocol and the owner opens it.
- **LEAN section:** positive-EV rows from families whose state permits surfacing
  as LEAN — every row stamped **"LEAN — unvalidated estimate."**
- **WATCH section:** priced rows held back by a named guard (unvalidated family
  hold, prior-only totals, stale quote, availability unverified). The hold reason
  shows on the row, not in a footnote.
- Ranking never mixes sections: a +30% WATCH row never appears above a +4% LEAN
  row as if it were "better." Within a section, rank by EV.
- Where a ranking is an artifact of a known construction defect (e.g. the NFL
  sides prior-compression pattern, issue #2384), the board says so at the top of
  the section, in plain words, before the table.

### 2.5 Parlay / SGP tools
A builder over rows already on the boards — it introduces no new prices.
- Combined price computed from the legs' captured DK prices.
- **Any combined probability/EV computed under independence must print the
  independence assumption on the ticket itself**, and must print a correlation
  warning naming the shared thesis when legs come from the same game or the same
  model view (same-game legs, same-direction totals stacks, teammates).
- Correlated clusters follow the standing grading rule: one thesis = one
  statistical position; the tool shows the cluster as one position with its legs
  listed, never as N independent bets.
- Boost tokens/promotions are displayed as captured facts (name, terms, expiry)
  and matched selection-by-selection in a separate boost-check block; a boost is
  **never folded into a straight-bet EV figure**.
- A parlay of WATCH rows is a WATCH parlay; labels inherit the weakest leg's
  label. No parlay may surface above the label its legs carry.

### 2.6 Results tracker (public record)
Every board row that was published pregame is graded against finals and kept,
**wins and losses both**, forever, unedited:
- Per-position accounting with correlated clusters counted once statistically,
  legs preserved individually, P&L shown separately and only as documented actual
  or explicitly labeled hypothetical equal-stake.
- Family-level running records with the family's validation state next to them
  (e.g. "NFL sides — DOES_NOT_BEAT_CLOSE (screen, 2018–2025) — forward test in
  progress, 0 of 4 slates").
- Voided/postponed selections stay on the record, struck as VOID with the ruling,
  never graded, never deleted.
- Rows published before their construction was committed (historical-record rows)
  are labeled HISTORICAL and never counted in any forward-test sample.
- The tracker never restates a past board. Corrections travel as new dated notes.

## 3. Row schema (normative)

One priced selection = one row. Fields marked † are mandatory; a row missing a
mandatory field does not render as priced — it renders BLOCKED with the missing
field named.

| Field | Notes |
|---|---|
| `sport` † | NBA / NFL / MLB / CFB |
| `league` † | e.g. NBA, NFL, MLB, NCAAF |
| `event` † | "Away Team @ Home Team" + start time with timezone |
| `game_id` | source ID where available (nflverse/ESPN/StatsAPI) |
| `market` † | ML, SPREAD, TOTAL, TEAM_TOTAL, PLAYER_POINTS, … (family registry name) |
| `family` † | registered family id + family validation state |
| `selection` † | team or player side as displayed |
| `player` | FULL name for props; `player_id` where the family requires it (NFL props) |
| `line` | null for ML |
| `side` | OVER/UNDER, home/away, YES (anytime-TD is Yes-only by rule) |
| `price_american` † | the DK price exactly as captured |
| `book` † | `DraftKings` (only book at launch) |
| `captured_at` † | ISO 8601 with timezone, from the capture — never render time, never retimestamped |
| `capture_type` | ENTRY / CLOSE / REFRESH (per Capture Spec V1) |
| `source_view` | page/view the price was read from (spec field) |
| `engine` † | engine id + version/commit that produced the projection |
| `model_projection` | projected score (games) or stat mean μ (props); null when unpriced |
| `model_p` | probability of the selection's side, incl. explicit push probability where the engine emits it |
| `fair_price_american` | derived from `model_p`; shown beside the book price |
| `implied_p_raw` | raw implied probability of the book price (vig included) |
| `implied_p_novig` | only from a real matched two-sided quote in the same capture |
| `edge_pct` † | EV per dollar vs the captured price, signed — **negative edges print negative** |
| `label` † | PLAY / LEAN / PASS / WATCH / BLOCKED / RESEARCH_ONLY (see §5) |
| `label_reason` † | exact code or plain reason, e.g. `WATCH_NFL_SIDE_UNVALIDATED`, `PLATE_APPEARANCE_PBP_POOL_UNBUILT`, `NO_ENGINE`, `CLOSE_STALE` |
| `cluster_id` | correlated-position id where legs share one thesis |
| `result` | post-game: WIN / LOSS / PUSH / VOID + final score/stat, filled by the tracker only |

Game rows additionally carry `model_home_mean`, `model_away_mean`,
`model_projected_total`, `model_projected_margin`.

## 4. Data contracts

**Inputs (the only inputs):**
1. **DK line archive** — `~/workspace/sportsedge/dk_line_archive/<sport>/YYYY-MM-DD/HHMM_ct.json`
   (filename = capture start, America/Chicago), plus its `INDEX.md`. NBA format per
   the capture jobs: ML/spread/total both sides both prices, team totals, player
   props limited to points/rebounds/assists O/U (both prices) and PRA combos where
   offered. A `{"status":"NO_BOARD"}` file is a valid input and renders an explicit
   empty board — absence is data.
2. **Committed capture records** for hand-captured boards (Capture Spec V1 records
   branches; e.g. the Oct 18 full-board capture in
   `~/workspace/sportsedge/dk_full_board_20261018/`).
3. **Priced-run outputs** from existing engines/runners (operative-run `card.json` /
   `lines.json` shape: paired quotes with `quote_captured_at`, per-lane estimates,
   `status` = the label, `play_gate` provenance). The board layer reads these; it
   does not re-price.
4. **Family registry** (repo `family_market_registry.py` state) for each family's
   registration + validation state — the board never hard-codes a family's state.
5. **Finals** for the tracker: official/public box scores with a named source per
   game, entered by the grading path — never edited after posting.

**Non-inputs (hard exclusions):** any external odds or projection feed; MySpariEdge
numbers as board data; social-media-only availability claims as facts (they may
appear in a game board's info pack labeled UNVERIFIED, as context only, and never
move a price, an EV, or a label); any price reconstructed after the fact.

**Freshness:** a row's actionability follows the standing freshness rules
(180-second rule for live RUN IT use; boards render the capture age on every row —
"captured 10:33 AM CT, 42 min before first pitch/tip"). Stale rows demote to
REFRESH REQUIRED rather than quietly aging. Pregame snapshots are labeled
PREGAME SNAPSHOT, never "closing lines"; a row earns CLOSE only under Capture
Spec V1 (last capture before start, ≤60 min before, else the CLV_MISSING reason
vocabulary applies in the tracker).

## 5. Label discipline (inherited, not negotiable)

- **PLAY** — validated families only. There are none. The label ships in the code
  disabled, gated on registry state + owner ruling.
- **LEAN** — positive-EV, unvalidated. Always rendered "LEAN — unvalidated estimate."
- **PASS — negative estimated EV** — shown with its negative EV, not hidden.
- **WATCH** — priced but not actionable; exact reason code on the row.
- **BLOCKED** — unpriced; exact blocker on the row.
- **RESEARCH_ONLY / RESEARCH_CANDIDATE_UNVALIDATED** — positive row demoted by a
  guard; never upgraded by ranking, layout, or color.
- Presentation: ranked best-to-worst within section; the standing emoji idiom
  (🟢🔥 / 🟡🔥 / 🔬🔥 research / ❄️ negative / 👁 WATCH) may decorate, never replace,
  the text label + reason. One side per market on any ranked view. Unvalidated
  disclosure and correlation warnings travel with the rows they describe —
  screenshots and exports of a board must carry them (they are part of the row
  schema, not page chrome).

## 6. Refresh cadence (tied to the capture jobs, not a new clock)

- **NBA boards** rebuild on each DK archive capture: morning ~10:21 AM CT and
  evening ~5:21 PM CT (plus the 5:00 PM pre-tip verification pass during the
  opening window). Between captures the board is static and shows its capture time.
- **NFL boards** rebuild on each committed Capture Spec V1 capture: entry captures
  on game week, close captures inside the 60-minute pre-kickoff window per game.
  Thursday's NE@CHI (Oct 22) is the first full entry+close cycle.
- **MLB boards** rebuild on committed captures for that day's board.
- **Tracker** updates once nightly after finals, from the grading run — never
  intra-game, never from unofficial live scores.
- No board auto-refreshes against a live site. If a capture didn't happen, the
  board says "no capture — last board <date/time>" instead of reaching for data.

## 7. Explicitly NOT copied from MySpariEdge

From the Oct 18 methodology audit of MySpariEdge (21 models/tools read first-hand):

1. **No floored-at-zero "Score."** Their Edge Lab Score never subtracts negative
   edge (floored at zero) — a display rank dressed as confidence. SportsEdge
   prints signed EV everywhere; a negative number looks negative.
2. **No price-less best bets.** Their Best Bets cards show no prices and no books
   and state no threshold or window. Every ranked row here carries the book, the
   captured price, the capture time, and the ranking rule.
3. **No undefined grades.** No letter grades (their Player Prop Picks grades have
   an undefined scale), no star ratings, no "lock" language. Labels are the
   standing SportsEdge set, each with a defined meaning and a reason code.
4. **No hidden methodology.** Their formulas/weights/thresholds are explicitly
   withheld. Every board names the engine + version per row and links the
   family's verdict record; a family with a negative verdict shows it on the board.
5. **No silent independence pricing.** Their Parlay Optimizer prices TD legs as
   independent, teammates included. Here the independence assumption, when used,
   prints on the ticket, and correlated legs are grouped as one position with the
   shared thesis named.
6. **No cherry-picked records.** Only two of their pages post records — both
   losing, neither prominent. Our tracker posts every published row, graded, with
   losses at the same size as wins, and family records shown next to the boards
   that sell the family's rows.
7. **No recalibration theater.** A model version is scored as it stood when it
   priced the games; a changed construction is a new version scored forward only.
   The tracker never restates history under a newer model.
8. **No price blending.** Their boards aggregate the market; ours bind to one
   book's captured price with its timestamp, because CLV against our own closes
   is the verdict path.

## 8. Open decisions for the owner (not assumed by this spec)

1. Board hosting/format for V1 (static markdown/HTML in the workspace vs web
   artifact) — spec is format-agnostic; the row schema is the contract.
2. NBA board scope in week 1 follows capture scope (game lines + pts/reb/ast +
   PRA). Expanding prop scope (threes/steals/blocks/turnovers/double-double) is a
   capture-scope ruling, not a board decision.
3. Whether Thursday's NE@CHI board prices under Part 2 / Part 2B depends on the
   pricing-owner assignment and the Part 2B freeze — the board renders whatever
   the committed engines produce, BLOCKED where they refuse.
4. PLAY stays unavailable until a family validates; opening it is an owner ruling
   per family, never a product default.


---

# PART 2 — PROTOTYPE SLATE BOARD (Oct 18, 2026, real capture)

# PROTOTYPE — NFL Slate Board, Sunday Oct 18, 2026

*Prototype rendering for the board product spec (SPEC.md), built only from real
captured data: DK capture Sun Oct 18, 10:33:02–10:33:32 CT (DraftKings, signed
out), priced on main `bfca7a420` (operative run `operative_run_20261018_nfl_slate/`).
**PREGAME SNAPSHOT — not closing lines.** Research only.*

> **PLAY: none. No validated families — PLAY is unavailable.**
> LEAN: none on this slate — 66 rows evaluated, **0 LEAN-eligible rows**;
> every positive-EV row below is a form-EV figure held at WATCH by a named
> guard (below), not a lean and not a measured edge.
>
> ⚠️ **Known construction artifact (issue #2384):** the game model is an
> unvalidated team-score heuristic whose means cluster in a narrow band
> (projected totals 41.1–44.5 across all 11 games), so it mechanically disagrees
> with every large market spread toward the underdog. The large positive "EVs"
> below are that artifact's output, **not measured edges**: the Elo challenger
> tested against closing lines returned **DOES_NOT_BEAT_CLOSE**, and NFL totals
> sit on a LEVEL hold (no absolute scoring-rate model — totals are prior-only).

Labels on every row: 👁 **WATCH** — sides `WATCH_NFL_SIDE_UNVALIDATED`
(owner-ruled #2384 hold), totals `WATCH_NFL_TOTAL_PRIOR_ONLY`.

## Slate at a glance

| Game (CT) | Model projection | DK total | DK spread | Highest-EV row (all WATCH) |
|---|---|---|---|---|
| Chicago @ Atlanta (12:00) | ATL 22.5 – CHI 21.2 (43.7) | 51.5 | CHI −1.5 | Under 51.5, EV +35.8% |
| NY Jets @ New England (12:00) | NE 22.8 – NYJ 20.6 (43.4) | 43.5 | NE −7.5 | Jets ML +275, EV +63.0% |
| Carolina @ Philadelphia (12:00) | PHI 21.5 – CAR 21.2 (42.7) | 39.5 | CAR −3 | Eagles ML +136, EV +20.5% |
| Tennessee @ Indianapolis (12:00) | IND 22.1 – TEN 19.0 (41.1) | 43.5 | IND −6.5 | Titans ML +235, EV +37.2% |
| Baltimore @ Cleveland (12:00) | CLE 22.0 – BAL 19.9 (41.9) | 39.5 | BAL −3 | Browns ML +142, EV +35.4% |
| Pittsburgh @ Tampa Bay (12:00) | TB 20.7 – PIT 21.1 (41.8) | 38.5 | PIT −1.5 | Over 38.5, EV +14.9% |
| New Orleans @ NY Giants (12:00) | NYG 22.4 – NO 20.2 (42.5) | 46.5 | NO −1.5 | Under 46.5, EV +15.1% |
| Arizona @ LA Rams (3:05) | LAR 22.7 – ARI 19.5 (42.2) | 51.5 | LAR −12.5 | Cardinals ML +550, EV +164.6% |
| LA Chargers @ Kansas City (3:25) | KC 23.7 – LAC 19.3 (43.0) | 41.5 | KC −7 | Chargers ML +310, EV +53.2% |
| Buffalo @ Las Vegas (3:25) | LV 22.7 – BUF 21.8 (44.5) | 53.5 | BUF −5.5 | Raiders ML +200, EV +57.6% |
| Dallas @ Green Bay (7:20) | GB 22.0 – DAL 20.8 (42.8) | 53.5 | GB −1.5 | Under 53.5, EV +51.4% |

*Late-window games were re-read in the afternoon full-board capture (3:00–3:19 PM
CT, `dk_full_board_20261018/nfl_late_full.json`); this board binds to the 10:33 AM
priced capture, and both reads are preserved in the capture record.*

## Ranked rows — WATCH section (by form EV, descending)

*No PLAY or LEAN rows exist on this slate. Ranking inside WATCH is for research
reading only; the #2384 artifact warning above applies to every row.*

| # | Selection | Price (DK) | Model p | Fair | EV | Label / reason |
|---|---|---|---|---|---|---|
| 1 | Arizona Cardinals ML | +550 | 40.7% | +146 | +164.6% | WATCH_NFL_SIDE_UNVALIDATED |
| 2 | NY Jets ML | +275 | 43.5% | +130 | +63.0% | WATCH_NFL_SIDE_UNVALIDATED |
| 3 | Las Vegas Raiders ML | +200 | 52.5% | −111 | +57.6% | WATCH_NFL_SIDE_UNVALIDATED |
| 4 | LA Chargers ML | +310 | 37.4% | +168 | +53.2% | WATCH_NFL_SIDE_UNVALIDATED |
| 5 | Under 53.5 (DAL@GB) | −108 | 78.6% | −367 | +51.4% | WATCH_NFL_TOTAL_PRIOR_ONLY |
| 6 | Under 51.5 (ARI@LAR) | −105 | 75.4% | −306 | +47.2% | WATCH_NFL_TOTAL_PRIOR_ONLY |
| 7 | Arizona Cardinals +12.5 | −108 | 75.1% | −301 | +44.6% | WATCH_NFL_SIDE_UNVALIDATED |
| 8 | Under 53.5 (BUF@LV) | −108 | 74.8% | −297 | +44.1% | WATCH_NFL_TOTAL_PRIOR_ONLY |
| 9 | Tennessee Titans ML | +235 | 40.9% | +144 | +37.2% | WATCH_NFL_SIDE_UNVALIDATED |
| 10 | Under 51.5 (CHI@ATL) | −112 | 71.8% | −254 | +35.8% | WATCH_NFL_TOTAL_PRIOR_ONLY |
| 11 | Cleveland Browns ML | +142 | 55.9% | −127 | +35.4% | WATCH_NFL_SIDE_UNVALIDATED |
| 12 | Cleveland Browns +3 | −102 | 63.0% | −184 | +27.5% | WATCH_NFL_SIDE_UNVALIDATED |

## Full game boards (all 66 priced rows)

### Chicago Bears @ Atlanta Falcons — model: ATL 22.528 – CHI 21.202 (total 43.73)
| Selection | Price | Model p | Fair | EV | Label |
|---|---|---|---|---|---|
| Chicago Bears ML | −120 | 46.1% | +117 | −15.4% | WATCH_NFL_SIDE_UNVALIDATED |
| Atlanta Falcons ML | +100 | 53.9% | −117 | +7.7% | WATCH_NFL_SIDE_UNVALIDATED |
| Chicago Bears −1.5 | −108 | 41.8% | +139 | −19.4% | WATCH_NFL_SIDE_UNVALIDATED |
| Atlanta Falcons +1.5 | −112 | 58.2% | −139 | +10.1% | WATCH_NFL_SIDE_UNVALIDATED |
| Over 51.5 | −108 | 28.2% | +254 | −45.6% | WATCH_NFL_TOTAL_PRIOR_ONLY |
| Under 51.5 | −112 | 71.8% | −254 | +35.8% | WATCH_NFL_TOTAL_PRIOR_ONLY |

### New York Jets @ New England Patriots — model: NE 22.834 – NYJ 20.578 (total 43.41)
| Selection | Price | Model p | Fair | EV | Label |
|---|---|---|---|---|---|
| NY Jets ML | +275 | 43.5% | +130 | +63.0% | WATCH_NFL_SIDE_UNVALIDATED |
| New England Patriots ML | −345 | 56.5% | −130 | −27.1% | WATCH_NFL_SIDE_UNVALIDATED |
| NY Jets +7.5 | −112 | 64.9% | −185 | +22.9% | WATCH_NFL_SIDE_UNVALIDATED |
| New England Patriots −7.5 | −108 | 35.1% | +185 | −32.4% | WATCH_NFL_SIDE_UNVALIDATED |
| Over 43.5 | −102 | 49.7% | +101 | −1.5% | WATCH_NFL_TOTAL_PRIOR_ONLY |
| Under 43.5 | −118 | 50.3% | −101 | −7.1% | WATCH_NFL_TOTAL_PRIOR_ONLY |

### Carolina Panthers @ Philadelphia Eagles — model: PHI 21.52 – CAR 21.16 (total 42.68)
| Selection | Price | Model p | Fair | EV | Label |
|---|---|---|---|---|---|
| Carolina Panthers ML | −162 | 49.0% | +104 | −20.8% | WATCH_NFL_SIDE_UNVALIDATED |
| Philadelphia Eagles ML | +136 | 51.0% | −104 | +20.5% | WATCH_NFL_SIDE_UNVALIDATED |
| Carolina Panthers −3 | −112 | 38.9% | +150 | −23.5% | WATCH_NFL_SIDE_UNVALIDATED |
| Philadelphia Eagles +3 | −108 | 58.3% | −150 | +15.0% | WATCH_NFL_SIDE_UNVALIDATED |
| Over 39.5 | −112 | 59.3% | −146 | +12.3% | WATCH_NFL_TOTAL_PRIOR_ONLY |
| Under 39.5 | −108 | 40.7% | +146 | −21.6% | WATCH_NFL_TOTAL_PRIOR_ONLY |

### Tennessee Titans @ Indianapolis Colts — model: IND 22.114 – TEN 18.976 (total 41.09)
| Selection | Price | Model p | Fair | EV | Label |
|---|---|---|---|---|---|
| Tennessee Titans ML | +235 | 40.9% | +144 | +37.2% | WATCH_NFL_SIDE_UNVALIDATED |
| Indianapolis Colts ML | −290 | 59.1% | −144 | −20.6% | WATCH_NFL_SIDE_UNVALIDATED |
| Tennessee Titans +6.5 | −108 | 59.7% | −148 | +15.0% | WATCH_NFL_SIDE_UNVALIDATED |
| Indianapolis Colts −6.5 | −112 | 40.3% | +148 | −23.7% | WATCH_NFL_SIDE_UNVALIDATED |
| Over 43.5 | −110 | 42.9% | +133 | −18.1% | WATCH_NFL_TOTAL_PRIOR_ONLY |
| Under 43.5 | −110 | 57.1% | −133 | +9.0% | WATCH_NFL_TOTAL_PRIOR_ONLY |

### Baltimore Ravens @ Cleveland Browns — model: CLE 21.994 – BAL 19.948 (total 41.94)
| Selection | Price | Model p | Fair | EV | Label |
|---|---|---|---|---|---|
| Baltimore Ravens ML | −170 | 44.1% | +127 | −30.0% | WATCH_NFL_SIDE_UNVALIDATED |
| Cleveland Browns ML | +142 | 55.9% | −127 | +35.4% | WATCH_NFL_SIDE_UNVALIDATED |
| Baltimore Ravens −3 | −118 | 34.3% | +184 | −33.9% | WATCH_NFL_SIDE_UNVALIDATED |
| Cleveland Browns +3 | −102 | 63.0% | −184 | +27.5% | WATCH_NFL_SIDE_UNVALIDATED |
| Over 39.5 | −112 | 57.2% | −134 | +8.2% | WATCH_NFL_TOTAL_PRIOR_ONLY |
| Under 39.5 | −108 | 42.8% | +134 | −17.5% | WATCH_NFL_TOTAL_PRIOR_ONLY |

### Pittsburgh Steelers @ Tampa Bay Buccaneers — model: TB 20.662 – PIT 21.148 (total 41.81)
| Selection | Price | Model p | Fair | EV | Label |
|---|---|---|---|---|---|
| Pittsburgh Steelers ML | −130 | 51.4% | −106 | −9.0% | WATCH_NFL_SIDE_UNVALIDATED |
| Tampa Bay Buccaneers ML | +110 | 48.6% | +106 | +2.0% | WATCH_NFL_SIDE_UNVALIDATED |
| Pittsburgh Steelers −1.5 | −115 | 47.0% | +113 | −12.0% | WATCH_NFL_SIDE_UNVALIDATED |
| Tampa Bay Buccaneers +1.5 | −105 | 53.0% | −113 | +3.4% | WATCH_NFL_SIDE_UNVALIDATED |
| Over 38.5 | −108 | 59.7% | −148 | +14.9% | WATCH_NFL_TOTAL_PRIOR_ONLY |
| Under 38.5 | −112 | 40.3% | +148 | −23.7% | WATCH_NFL_TOTAL_PRIOR_ONLY |

### New Orleans Saints @ New York Giants — model: NYG 22.372 – NO 20.158 (total 42.53)
| Selection | Price | Model p | Fair | EV | Label |
|---|---|---|---|---|---|
| New Orleans Saints ML | −108 | 43.6% | +129 | −16.1% | WATCH_NFL_SIDE_UNVALIDATED |
| NY Giants ML | −112 | 56.4% | −129 | +6.8% | WATCH_NFL_SIDE_UNVALIDATED |
| New Orleans Saints −1.5 | +105 | 39.3% | +154 | −19.4% | WATCH_NFL_SIDE_UNVALIDATED |
| NY Giants +1.5 | −125 | 60.7% | −154 | +9.2% | WATCH_NFL_SIDE_UNVALIDATED |
| Over 46.5 | −105 | 38.4% | +160 | −25.0% | WATCH_NFL_TOTAL_PRIOR_ONLY |
| Under 46.5 | −115 | 61.6% | −160 | +15.1% | WATCH_NFL_TOTAL_PRIOR_ONLY |

### Arizona Cardinals @ Los Angeles Rams — model: LAR 22.726 – ARI 19.504 (total 42.23)
| Selection | Price | Model p | Fair | EV | Label |
|---|---|---|---|---|---|
| Arizona Cardinals ML | +550 | 40.7% | +146 | +164.6% | WATCH_NFL_SIDE_UNVALIDATED |
| Los Angeles Rams ML | −800 | 59.3% | −146 | −33.3% | WATCH_NFL_SIDE_UNVALIDATED |
| Arizona Cardinals +12.5 | −108 | 75.1% | −301 | +44.6% | WATCH_NFL_SIDE_UNVALIDATED |
| Los Angeles Rams −12.5 | −112 | 24.9% | +301 | −52.8% | WATCH_NFL_SIDE_UNVALIDATED |
| Over 51.5 | −115 | 24.6% | +306 | −54.0% | WATCH_NFL_TOTAL_PRIOR_ONLY |
| Under 51.5 | −105 | 75.4% | −306 | +47.2% | WATCH_NFL_TOTAL_PRIOR_ONLY |

### Los Angeles Chargers @ Kansas City Chiefs — model: KC 23.68 – LAC 19.27 (total 42.95)
| Selection | Price | Model p | Fair | EV | Label |
|---|---|---|---|---|---|
| LA Chargers ML | +310 | 37.4% | +168 | +53.2% | WATCH_NFL_SIDE_UNVALIDATED |
| Kansas City Chiefs ML | −395 | 62.6% | −168 | −21.5% | WATCH_NFL_SIDE_UNVALIDATED |
| LA Chargers +7 | −105 | 56.1% | −136 | +12.3% | WATCH_NFL_SIDE_UNVALIDATED |
| Kansas City Chiefs −7 | −115 | 41.1% | +136 | −20.3% | WATCH_NFL_SIDE_UNVALIDATED |
| Over 41.5 | −110 | 54.3% | −119 | +3.6% | WATCH_NFL_TOTAL_PRIOR_ONLY |
| Under 41.5 | −110 | 45.7% | +119 | −12.7% | WATCH_NFL_TOTAL_PRIOR_ONLY |

### Buffalo Bills @ Las Vegas Raiders — model: LV 22.672 – BUF 21.802 (total 44.47)
| Selection | Price | Model p | Fair | EV | Label |
|---|---|---|---|---|---|
| Buffalo Bills ML | −245 | 47.5% | +111 | −33.2% | WATCH_NFL_SIDE_UNVALIDATED |
| Las Vegas Raiders ML | +200 | 52.5% | −111 | +57.6% | WATCH_NFL_SIDE_UNVALIDATED |
| Buffalo Bills −5.5 | −108 | 32.1% | +212 | −38.2% | WATCH_NFL_SIDE_UNVALIDATED |
| Las Vegas Raiders +5.5 | −112 | 67.9% | −212 | +28.5% | WATCH_NFL_SIDE_UNVALIDATED |
| Over 53.5 | −112 | 25.2% | +297 | −52.3% | WATCH_NFL_TOTAL_PRIOR_ONLY |
| Under 53.5 | −108 | 74.8% | −297 | +44.1% | WATCH_NFL_TOTAL_PRIOR_ONLY |

### Dallas Cowboys @ Green Bay Packers — model: GB 21.958 – DAL 20.848 (total 42.81)
| Selection | Price | Model p | Fair | EV | Label |
|---|---|---|---|---|---|
| Dallas Cowboys ML | −105 | 46.8% | +114 | −8.7% | WATCH_NFL_SIDE_UNVALIDATED |
| Green Bay Packers ML | −115 | 53.2% | −114 | −0.5% | WATCH_NFL_SIDE_UNVALIDATED |
| Dallas Cowboys +1.5 | −118 | 51.1% | −105 | −5.5% | WATCH_NFL_SIDE_UNVALIDATED |
| Green Bay Packers −1.5 | −102 | 48.9% | +105 | −3.2% | WATCH_NFL_SIDE_UNVALIDATED |
| Over 53.5 | −112 | 21.4% | +367 | −59.5% | WATCH_NFL_TOTAL_PRIOR_ONLY |
| Under 53.5 | −108 | 78.6% | −367 | +51.4% | WATCH_NFL_TOTAL_PRIOR_ONLY |

## Prop board — captured, not priced on this run (BLOCKED with reason)

The full-board capture held prop sections the slate run did not price. They render
here as captured prices with **no model number** — the board does not invent one.
Example, Chicago @ Atlanta TD scorers (DK, captured ~10:48 AM CT; full board 27
entries incl. No TD Scorer):

| Player | Anytime | First TD | 2+ TDs | Status |
|---|---|---|---|---|
| Bijan Robinson | −275 | +350 | +185 | BLOCKED — not priced on this run |
| D'Andre Swift | −180 | +425 | +310 | BLOCKED — not priced on this run |
| Drake London | +105 | +950 | +650 | BLOCKED — not priced on this run |
| Rome Odunze | +165 | +1200 | +1200 | BLOCKED — not priced on this run |
| Brian Robinson Jr. | +190 | +1200 | +1500 | BLOCKED — not priced on this run |
| Colston Loveland | +190 | +1400 | +1500 | BLOCKED — not priced on this run |
| Luther Burden III | +190 | +1300 | +1500 | BLOCKED — not priced on this run |
| Kyle Pitts Sr. | +320 | +2000 | +3000 | BLOCKED — not priced on this run |
| Caleb Williams | +350 | +2000 | +4000 | BLOCKED — not priced on this run |
| Cole Kmet | +500 | +2800 | +6500 | BLOCKED — not priced on this run |

*Reason:* the anytime-TD family prices only under its locked forward-test setup
(engine + rules committed Oct 18; first counted slate Thu Oct 22) — an Oct 18
afternoon price with no committed pregame pricing run stays unpriced rather than
retro-priced. CHI@ATL passing markets (Penix Jr., Williams — yards / TDs /
interceptions / attempts) were likewise captured (~10:49–10:50 AM CT) and are
unpriced on this board for the same reason: the Part 2 forward test, not this
slate run, is their pricing path. Captured alternate ladders (CHI@ATL: 46 spread
rungs, 46 total rungs) are on the game board in the full product; omitted here
for length, present in `dk_full_board_20261018/nfl_noon_partial.json`.

## Tracker preview (this board, graded)

From the grading record at `operative_run_20261018_nfl_slate/GRADE_AND_REVIEW.md`
(nightly grading, Oct 18, 2026; finals: Sportradar + corroboration) — figures
carried from that record, checkable against it:
- All 66 rows were WATCH — no P&L is counted for WATCH rows.
- The informative subset — the 30 rows with positive form EV (the model's
  candidate direction per market): **11 W / 19 L**.
- Side candidate rows (form EV ≥ +2%): **19 of 20 were underdog-backed** — the
  #2384 prior-compression signature, reproduced again.
- Free-bet context (not a board row; placement unknown to the record): the
  owner's conditional pick **Cardinals ML +550 WON** (Arizona 18, Rams 16);
  Jets ML +275 LOST (Patriots 26, Jets 19). No actual P&L is stated.
- Standing verdicts unchanged by one slate: NFL sides **DOES_NOT_BEAT_CLOSE**
  (challenger screen, Δ log loss vs close +0.02916 [0.02098, 0.03792],
  n=2,119, 2018–2025); totals family on LEVEL hold. Tonight is consistent with
  those verdicts, not new proof of them — and the Cardinals win does not
  validate the construction that produced it.

*Factor audit (from the priced run): QB/injury heuristic used for all 11 games
from ESPN injuries, completeness UNKNOWN; rest and recent-form contributions
disabled (zero) pending incremental-value proof; market odds as model features:
rejected, never priced.*


---

# PART 3 — BUILD ORDER

# Slate Boards — Build Order

Phased so each phase ships a board that is honest at its scope. A phase is done
when its board renders real captured slates end-to-end with labels/reasons intact
and its gate checks pass — not when the code merely exists.
Gates in force at **every** phase (never phased in later): research-only framing;
zero validated families, so PLAY renders empty; prices only from our own
timestamped DK captures; labels + reason codes on every row; no external prices
or projections as board data; correlated legs disclosed, independence assumption
printed wherever it is used; a missed capture renders as "no capture," never as
reconstructed data.

---

## Phase 0 — Board data layer (foundation; no UI opinions yet)

**Inputs:** DK line archive files (`dk_line_archive/<sport>/YYYY-MM-DD/HHMM_ct.json`
+ `INDEX.md`); committed Capture Spec V1 records; operative-run outputs
(`card.json`, `lines.json`); family registry state from the repo.
**Outputs:**
- A normalizer that maps each input shape into the SPEC §3 row schema, preserving
  `captured_at`, `capture_type`, engine id/version, label and label reason
  verbatim. No field is invented in normalization: a missing projection stays
  null and the row becomes BLOCKED with the reason.
- A board document model (per sport/day: slate view, game views, prop rows,
  unpriced/refusal list) serializable to markdown/HTML.
- Fixture tests: the Oct 18 NFL full-board capture + operative slate reproduce
  as a board byte-comparable to `prototype_board.md`'s numbers; the Oct 19 NBA
  `NO_BOARD`/first-capture files round-trip.
**Gates:** schema tests fail closed (a row missing price, timestamp, engine, or
label cannot render as priced); double-read prices keep both timestamps;
UNREADABLE capture sections survive normalization as UNREADABLE.

## Phase 1 — NBA slate board + game boards (first — captures start Oct 19, season tips Oct 20–21)

**Inputs:** NBA archive captures (AM ~10:21 CT, PM ~5:21 CT) — ML/spread/total
both sides, team totals, pts/reb/ast O/U + PRA combos; the NBA ratings engine
(committed defaults, the RAW construction chosen for testing — the shipped
variant whose totals copy the DK line is untestable and must not price a board).
**NBA total rows carry an explicit named reason, never a generic WATCH tag:**
`WATCH_NBA_TOTAL_RAW_MODEL` — held-out market leg: the RAW construction's
totals add no measured accuracy beyond the line (market-leg test on the
2015–2021 SBR holdout was worse than the close; bias diagnosis Oct 18:
NO_BIAS vs reality, BIAS_UNSTABLE vs close). Every NBA totals row renders
with that reason attached until a new version earns a different one.
**Outputs:** daily NBA slate board (every game, model projected score/total/
margin, best-row-per-game with label), game boards with team totals, prop edge
board for pts/reb/ast/PRA with the family's NO-GO banner (readiness verdict:
0 GO / 19 NO-GO — market never measured for props; forward test vs these
captures is the verdict path).
**Gates:** every NBA family currently resolves BLOCKED/UNVALIDATED in the
registry — the board launches with game rows priced as research estimates
under WATCH/RESEARCH labels and prop rows exactly as the forward protocol
admits; DNP rows in results data filtered downstream (tracker concern, noted
here); board must render an explicit empty board on `NO_BOARD` days.

## Phase 2 — NFL slate board + game boards (for Thu Oct 22 NE@CHI and Sunday slates)

**Inputs:** Capture Spec V1 captures (Thu: full board entry pregame + close in
the 6:15–7:15 PM CT window; other games: four scored prop markets + anytime-TD
Yes board + ML/spread/total, entry + close); committed Part 2 construction for
the four prop markets; the anytime-TD engine under its locked rules; the
canonical runner for game rows.
**Outputs:** NFL slate board; game boards incl. TD-scorer section (Yes-only,
with UNPRICED rows and their reasons listed); prop edge board for
pass/rush/rec yards + receptions; ranked view where side rows render
`WATCH_NFL_SIDE_UNVALIDATED` and totals `WATCH_NFL_TOTAL_PRIOR_ONLY` until a
family's state changes in the registry — the #2384 artifact warning pinned
above the side rankings.
**Gates:** Part 2 rows count toward the forward test only if priced by the
committed construction from captures committed as taken (freeze order is a
repo fact, checked at audit); close rows follow the Capture Spec V1 vocabulary
(CLVMISSING reasons named, never filled); nothing about the board build touches
the frozen preregistrations. Who prices Thursday's board is an owner assignment
that must land before this phase is exercised on Oct 22.

## Phase 3 — MLB board

**Inputs:** committed DK captures per day's board (Oct 18 ALCS G5 capture is
the shape reference: game lines, F5/period boards, pitcher props, batter
suites, correct scores); existing MLB engines (game-path runner, batter
empirical engine on the phone path, pitcher-K construction under its frozen
protocol).
**Outputs:** MLB slate board (in October: the single postseason game, rendered
fully); game board with period and prop sections; prop edge board limited to
families with engines, everything else BLOCKED with its gate named
(`PLATE_APPEARANCE_PBP_POOL_UNBUILT`, `NO_MODEL_OR_MARKET`, registration states).
**Gates:** pitcher-K rows surface only under the frozen forward protocol's
terms (paired two-sided main lines, price cap, protocol count on the tracker);
F5 `eligible=false` untouched; one-sided milestone rows priced single-side with
NO_DEVIG labeling or refused by validation state — never paired with invented
opposite odds.

## Phase 4 — Results tracker

**Inputs:** published board snapshots (immutable as rendered), nightly grading
outputs (`GRADE_AND_REVIEW.md` per operative run), official finals with named
sources.
**Outputs:** per-family and per-board public records: every published row with
WIN/LOSS/PUSH/VOID, correlated positions counted once statistically with legs
preserved, P&L separated (actual documented, or labeled hypothetical
equal-stake), family validation state + forward-test progress (slates/rows/
games vs the frozen gates) displayed beside the record.
**Gates:** no restatement of published boards; VOID rulings recorded with the
ruling, never deleted; HISTORICAL rows (published before their construction
was committed) labeled and excluded from forward samples; one night's results
never presented as recalibration evidence.

## Phase 5 — Parlay / SGP tools

**Inputs:** rows already on the boards (their captured DK prices only); DK
boost/promo facts as captured (name, terms, expiry).
**Outputs:** a builder rendering a ticket with combined price from leg prices;
combined probability/EV only with the **independence assumption printed on the
ticket** plus a correlation warning naming any shared game/thesis; cluster
grouping (one thesis = one position, legs listed); label = weakest leg's label;
a boost-check block matching boosts selection-by-selection (never folded into
straight-bet EV).
**Gates:** no leg can be added that isn't a current board row at a captured
price; SGP/parlay-only boost restrictions stated as such; the tool produces
research tickets only — no bet placement, no account action, ever.

---

## Explicitly out of scope for this build

- NHL / UFC / PGA boards (parked). CFB pricing (registry gate stands; board
  shows BLOCKED fixtures only, pending the owner's separate ruling).
- Any new model or engine. Boards consume existing engines; an engine gap
  renders as BLOCKED/NO_ENGINE, which is the board telling the truth.
- Capture expansion (new sports/markets/sections) — capture scope changes are
  owner rulings executed by the capture lane, not side effects of board work.
- Live/in-game boards. Pregame snapshots and closes only.


---

# APPENDIX — MYSPAREDGE METHODOLOGY AUDIT (Oct 18, 2026)

# MySpariEdge Methodology Audit — Oct 18, 2026

- **Author:** Rocky — Isaac's main-chat agent (the Muse / captures lane). Sole reader and author of this audit.
- **Date of underlying read:** October 18, 2026 — 21 MySpariEdge models/tools read that day (public and member pages; member access via Isaac's sign-in, completed by Isaac himself).
- **Delivered:** to Isaac in the main chat on the evening of Oct 18, 2026.
- **Status:** RESEARCH CONTEXT ONLY. This audit is research context, **not** evidence about SportsEdge models. All MySpariEdge numbers are source-labeled wherever used and are never blended into SportsEdge numbers. SportsEdge prices bind only to paired DraftKings captures.

---

## Findings

### 1. Player Props Edge — the only model that states a backtest basis
- **Model%** = calibrated selected-side win rate from 2023–25 testing.
- **Edge%** = Model% − implied probability **with the margin (vig) in**.
- Their **"Score" never subtracts negative edge — it is floored at zero.** It is a display rank, not a confidence rating.
- NFL props lock 90 minutes before kickoff.

### 2. Only two pages post records — and both are losing
**Edge Lab** (frozen NFL 2026 archive, 3,991 selections; flat-1u ROI negative in *every* Score band):
| Score band | ROI | n |
|---|---|---|
| <150 | −7.3% | 1,045 |
| 150–199.9 | −3.1% | 2,349 |
| 200–249.9 | −2.9% | 461 |
| 250+ | −5.5% | 90 |
| "Unknown" band | +12.6% | — |

The top-filter "systems" showing +16.7% to +28.5% are self-flagged **EARLY SAMPLE** on the page itself.

**Model Bets Tracker** (MLB, Oct 8–17): 20–23, −8.4u, −19.5% ROI, labeled "Small sample" on the page.

### 3. Best Bets — UNVERIFIABLE
No stated selection threshold or window. The cards show **no prices and no books**, so the picks cannot be checked against any market or reproduced after the fact.

### 4. "How Our Models Work"
Inputs are listed, and projections freeze at lineup lock — but weights, formulas, and thresholds are **explicitly withheld**, and no backtest seasons or sample sizes are given anywhere on the page.

### 5. NRFI/YRFI — their most disciplined page
- Starter hold probability is driven by season K/9.
- The first-inning record is shrunk toward the league baseline and **capped below the K/9 weight**.
- A top-3 OBP lineup adjustment is applied.
- Non-inputs are stated explicitly — the only page that says what it does *not* use.

### 6. Touchdowns
- **Model%** = P(≥1 rush/rec TD), which matches DraftKings settlement.
- The **Parlay Optimizer prices TD legs as INDEPENDENT, teammates included** — no correlation adjustment.
- Week 6 board top: Derrick Henry 67.1%; Christian McCaffrey 56.6% with Edge −16.7% (i.e., their own board showed the most likely scorer as a strongly negative-edge bet at the posted price).

### 7. No stated methodology at all
- **Player Prop Picks:** letter grades with the scale undefined.
- **Parlay Builder:** marked BETA; no methodology stated.

---

## Standing conclusions (adopted by Isaac in the main chat, Oct 18, 2026 — as recorded in the author's main-chat record)

1. This audit is **research context, NOT evidence about SportsEdge models**. A competitor's weak disclosure says nothing about whether SportsEdge's constructions win or lose; SportsEdge verdicts come only from SportsEdge's own tests against prices.
2. **All MySpariEdge numbers stay source-labeled, never blended** into SportsEdge numbers, prices, or EV estimates.
3. Where SportsEdge adopts a MySpariEdge-style *presentation* idea, it does so under SportsEdge discipline: real prices and books shown, negative edge shown as negative, independence assumptions stated on the card, and full records (wins and losses) published.
