# VERIFIED MODELS — TAXONOMY EXTENSION: game props · SGP · live · NHL re-entry · PGA · UFC · DWCS

Written Oct 27, 2026 (America/Chicago), extending
`VERIFIED_MODELS_GAP_FILL_PLAN_20261027.md` (Phase 1 plan, same date). The base
plan's 26 inventory lines and statuses are **unchanged**; this document adds the
families and sports the owner confirmed after Phase 1 closed:

- Oct 27, 2026 ~23:03 CT: the program covers all sports and models — "Totals
  sides player and team props and game props SGP live betting."
- Oct 27, 2026 ~23:04 CT: "Nothing is paused anymore. We're going all out nba
  nfl CFB cbb nhl pga ufc DWCS GO" — the Oct 25 NHL pause is **lifted**, and
  PGA, UFC, and DWCS enter the program.

## Standing law carried into this extension (unchanged)

- VERIFIED (per the owner's Oct 27, 2026 ~22:53 CT repeal of the 50-pick gate)
  = a construction that has passed its **preregistered chronological
  out-of-sample validation against BOTH the existing model and a contemporaneous
  market baseline**. Forward clocks keep grading (CLV/ROI reported) but no
  longer gate the label. **Nothing in this document is verified, and nothing
  here passes anything tonight.** VERIFIED count across every line in this
  extension: **0**.
- FAILED constructions stay retired; replacements are new constructions.
  Historical data seen by a failed construction is DESIGN data only; no
  backfill, ever.
- PAPER / research only. No staking authority is created by this document.
- Every counting baseline is timestamped DraftKings capture. The lines lane
  writes each game **at most twice** — T-1H and FINAL, both pregame. There is
  **no in-play capture scope** anywhere in the program today (see G8).
- Status vocabulary for new lines: NO_CONSTRUCTION · NO_DATA · PARTIAL
  (construction or capture exists in some form; validation, a baseline leg, or
  a required input is missing — the basis says which).

## Grounding convention

Every "DraftKings posts X" claim below is tied to a repo artifact read for
this extension (cited inline) or is explicitly labeled **[DK-general]** —
general knowledge of DK's book, not grounded in a repo capture record.
Repo evidence wins over general knowledge wherever they differ.

Artifacts read for this extension: the Phase 1 plan (base document);
`docs/market_coverage_phase7.md` (the repo's DK market-coverage matrix,
2026-10-11); `docs/live_inplay.md` (Phase 6 live repricing); `docs/NBA_FEASIBILITY_2026-10-11.md`;
`docs/PGA_MODEL_STATUS.md`; `config/ufc_market_surface.json`;
`config/ufc_330_current.json`; `config/dwcs_s10w3_2026-08-25.json`;
`docs/ufc_model_design.md`; `sportsedge/sports/nhl/market_capabilities.py`;
`config/research/nhl_public_baseline_validation_prereg_v1.json`;
`.github/ISSUE_TEMPLATE/nhl-lines.yml`; `scripts/render_football_board_card.py`;
`scripts/run_cfb_paper_market.py`; `sportsedge/card_correlation.py` (via
`tests/test_card_correlated_stacks.py`); `research/nba_secondary_prop_20261020/SCREEN_SPEC_DRAFT.md`;
`research/cbb_season_prep_20261020/READINESS_CONTRACT_DRAFT.md`.

**Freeze-coverage check:** this file's path was checked against all 11 bundles
in `config/freeze_reconciliation_registry_v1.json` on main (318377dfa). No
bundle's coverage prefixes or paths cover `research/` — the path is **not
governed**. No other path is touched by the PR carrying this document.

---

# 1. THE NEW GRID

## 1A. The three new families × the five Phase 1 sports

| Sport | Game props | SGP (same-game parlays) | Live in-play |
|---|---|---|---|
| NFL | **PARTIAL** | **NO_CONSTRUCTION** | **PARTIAL** (+ NO_DATA for validation) |
| CFB | **PARTIAL** | **NO_CONSTRUCTION** | **PARTIAL** (+ NO_DATA for validation) |
| NBA | **NO_CONSTRUCTION** | **NO_CONSTRUCTION** | **NO_CONSTRUCTION** + **NO_DATA** |
| CBB | **NO_CONSTRUCTION** | **NO_CONSTRUCTION** | **NO_CONSTRUCTION** + **NO_DATA** |
| MLB | **PARTIAL** | **NO_CONSTRUCTION** | **PARTIAL** (strongest live evidence in the program; still not validated vs a market baseline) |

Team props note: "team props" in the owner's taxonomy maps to team totals
(already inventoried in the base plan for NFL/CFB/NBA/CBB/MLB) plus
team-scoped game props (team to score first, team race to X) — those live in
the game-props rows below, not in a separate grid.

## 1B. NHL — re-entered Oct 27, 2026 (no Phase 1 inventory existed)

Status: **RE-ENTERED** by the owner's Oct 27 ~23:04 CT ruling. The intake /
parser surface is on main (`sportsedge/nhl_lines_intake.py`,
`.github/ISSUE_TEMPLATE/nhl-lines.yml`); capture resumes under the standing
T-1H/FINAL cadence. NHL's "second attempt" proceeds from the public-baseline
work below — it does not resurrect any first-attempt construction.

| NHL family | Status | Basis (one line; detail in §2.6) |
|---|---|---|
| Moneyline / puck line / game total | PARTIAL | Public-boxscore baseline construction exists under a frozen research validation prereg; the capability contract still fails every NHL market closed (`REQUIRES_ENGINE`) until the engine emits the required PIT state. |
| Team totals | PARTIAL | Registered in the capability contract, derivable only from the same shared final-goal distribution as the game lines — same construction leg, same gate. |
| Period lines (period ML / period total, regulation ML) | NO_CONSTRUCTION | Registered `REQUIRES_ENGINE` (period goal paths required); no engine output admitted. |
| Player props (shots, points, goals, assists) | NO_CONSTRUCTION | Registered `REQUIRES_ENGINE`; the capture template itself marks goal/point/assist props `NO_MODEL` on purpose. |
| Goalie saves / player blocks / player hits | NO_CONSTRUCTION | Registered `REQUIRES_ENGINE` (opponent shot paths, PIT role state); nothing admitted. |
| Game props (first goal, period specials, race markets) | NO_CONSTRUCTION | Unregistered markets fail closed `NO_ENGINE` in the capability contract. DK posts NHL game props [DK-general]. |
| SGP | NO_CONSTRUCTION | No SGP path anywhere in the NHL stack. DK posts NHL SGP [DK-general]. |
| Live in-play | NO_CONSTRUCTION + NO_DATA | The Phase 6 live build covers MLB/NFL/CFB only; no NHL live machinery and no in-play capture. DK posts NHL in-play markets [DK-general]. |

## 1C. PGA — new sport (enters with an existing engine; enters honestly)

Repo evidence (`docs/PGA_MODEL_STATUS.md`, `sportsedge/pga_engine.py`,
`sportsedge/pga/`, `config/pga_benchmark_methodology.json`) shows a joint
field-simulation engine already on main with a frozen benchmark-methodology
contract — and an explicit in-repo warning: **"No PGA market family is
promoted merely by merging this implementation"** and "Code availability is
not promotion evidence." No point-in-time historical/forward evidence exists
yet for any family. Every PGA line below is therefore PARTIAL at best.

| PGA family | Status | Basis |
|---|---|---|
| Outrights (winner) | PARTIAL | Pre-event simulation readout exists; benchmarked as an exhaustive N-way field (`MULTIPLICATIVE_NWAY_V1`, complete field mandatory, partial-field normalization blocked). Zero validation evidence. DK posts outrights for every tour event [DK-general]; the engine's readout set is the repo grounding. |
| Top-5 / top-10 / top-20 finishes | PARTIAL | Simulation readouts exist (raw probability + dead-heat-adjusted expected payout share). Benchmark treats TOP_K as a binary proposition per golfer requiring paired YES/NO prices; cross-player normalization forbidden. Zero validation evidence. |
| Head-to-head matchups | PARTIAL | Event H2H win/loss/push readout exists; benchmark uses paired two-way de-vig with pushes tracked separately. Zero validation evidence. |
| Make-cut | PARTIAL | Readout exists with top-N-and-ties cut semantics; binary per golfer, paired YES/NO required. (In the owner's list only implicitly; recorded because the engine carries it.) |
| Round props | PARTIAL (FRL only) / NO_CONSTRUCTION (rest) | First-round-leader is a simulation readout and is benchmarked like outrights (N-way). Other round props (round-score O/U, leader after a later round, round matchups as a separate family) have no readout. DK posts round-leader and round-score markets [DK-general]. |
| SGP | NO_CONSTRUCTION | No parlay/joint-bet pricing path; the Phase 7 matrix records SGPs NOT_WIRED program-wide. DK offers golf parlays on featured events [DK-general]. |
| Live in-play | PARTIAL | A live module exists (`sportsedge/pga/`: leaderboard state as the simulation starting point, bounded in-round updates, immutable hash-verified snapshots, independent freshness checks). Live cut-event continuation is explicitly blocked (cut state not carried). Zero promotion evidence. DK posts in-play golf markets during rounds [DK-general]. |

## 1D. UFC — new sport (one market on the engine surface; the rest is explicit)

Repo evidence (`config/ufc_market_surface.json`) is unusually explicit: the
surface supports exactly one market and names the rest as
`unsupported_without_new_engine`. Governance in the same file:
`paired_prices_required`, `fighter_snapshot_required`,
`promotion_inherited_from_code_presence: false`.

| UFC family | Status | Basis |
|---|---|---|
| Moneyline (H2H) | PARTIAL | The surface's only supported market, engine `UFC_FIGHT_SIM` (`sportsedge/ufc_engine.py`, `ufc_history.py`, `ufc_training.py` exist). But `automatic_model_inputs: false` — model inputs are not automated — and `docs/ufc_model_design.md` requires an untouched holdout before official promotion; no promotion is recorded. |
| Method of victory (KO/TKO, submission, decision; incl. win-by-X splits) | NO_CONSTRUCTION | Named unsupported on the surface: `METHOD_OF_VICTORY`, `WIN_BY_KO_TKO`, `WIN_BY_SUBMISSION`, `WIN_BY_DECISION`. DK posts method markets on every UFC card [DK-general]. |
| Round totals / round props (total rounds O/U, round of victory, goes-the-distance) | NO_CONSTRUCTION | Named unsupported on the surface: `TOTAL_ROUNDS`, `ROUND_OF_VICTORY`, `FIGHT_GOES_DISTANCE`. DK posts round totals and distance markets [DK-general]. |
| SGP | NO_CONSTRUCTION | Not on the surface; no joint-pricing path. DK posts UFC SGPs [DK-general]. |
| Live in-play | NO_CONSTRUCTION + NO_DATA | `scripts/build_ufc_live_inputs.py` builds event-card inputs (with a freshness window), not in-play repricing; no in-play capture exists. DK posts in-play lines during UFC events [DK-general]. |

## 1E. DWCS — new sport (the UFC family set, with a thin-data flag on everything)

DWCS (Dana White's Contender Series) rides the UFC surface: an event card
definition exists on main (`config/dwcs_s10w3_2026-08-25.json`, Season 10
Week 3), and the UFC surface contract carries the governance flag
`dwcs_requires_event_specific_validation: true`. **Thin-data flag (applies to
every DWCS line):** many DWCS fighters are debutants or near-debutants with
little or no recorded pro data; the repo's own card note states the rule —
"Missing historical fighter data must remain uncertainty, never imputed as
certainty."

| DWCS family | Status | Basis |
|---|---|---|
| Moneyline (H2H) | PARTIAL + NO_DATA (per-fighter history) | Inherits the UFC_FIGHT_SIM surface slot, gated on event-specific validation that does not exist yet; for many bouts the binding constraint is not the engine but the absence of fighter history to feed it. |
| Method of victory | NO_CONSTRUCTION | Same unsupported list as UFC. DK posts method markets for DWCS bouts [DK-general]. |
| Round totals / round props | NO_CONSTRUCTION | Same unsupported list as UFC. DK posts round totals for DWCS bouts [DK-general]. |
| SGP | NO_CONSTRUCTION | No joint-pricing path. DK posts DWCS SGPs on some cards [DK-general]. |
| Live in-play | NO_CONSTRUCTION + NO_DATA | No in-play engine, no in-play capture. DK posts in-play lines during DWCS events [DK-general]. |

---

# 2. PER-FAMILY DETAIL — what DK posts, what a construction needs, what capture is missing

## 2.1 Game props

**NFL — PARTIAL.** The Phase 7 coverage matrix (`docs/market_coverage_phase7.md`,
read for this extension) built and harness-tested the game-prop surface
against 2024-season data: winning-margin bands (`MARGIN_BAND`) shipped as
IN_BUILD with a CONDITIONAL_PASS vs a naive baseline (NFL Brier 0.0864 vs
0.0876, n=1,280) — candidate-vs-naive only, market-baseline leg missing, so
this is diagnostic evidence, not validation under current law. The rest of
the DK football game-prop board is blocked with named reasons in the same
matrix: first TD scorer — `NO_VERIFIED_FIRST_SCORING_ATTRIBUTION`; team
first-to-score and race-to-X — `NO_VERIFIED_SCORING_TIMING_MODEL`; exact
score — `NO_JOINT_SCORE_DISTRIBUTION_WITH_CORRELATION` (football normal
marginals do not form a joint). Quarter lines sit adjacent (base plan:
NO_CONSTRUCTION as a clock family; Phase 7 found quarter spread/ML
conditional-pass vs naive and quarter totals/team totals FAILED vs naive —
the failed constructions are not revived by this extension).
*Needs:* play-by-play scoring-timing distributions (first-score, race) and
first-scoring attribution per player (first TD) — performance data exists
(nflverse PBP, base plan §3.1); what is missing is the timing-distribution
construction and its prereg. Exact score needs the joint-distribution layer
(G10), the same layer SGP needs. *Capture:* DK game props are not in the
lane's parser-safe grammar as countable rows today; the plan already records
adjacent material (kicking/ST-DEF) arriving as issue comment material,
one-sided — one-sided quotes cannot be no-vigged and cannot count.
**CFB — PARTIAL**, identically structured: margin bands IN_BUILD /
CONDITIONAL_PASS vs naive (Brier 0.0878 vs 0.0891, n=4,230); first-score /
race / exact score blocked on the same three named gaps; plus CFB's own
overlay — no PIT QB designations (G3) degrades every timing model built on
score paths. **NBA — NO_CONSTRUCTION:** `docs/NBA_FEASIBILITY_2026-10-11.md`
classifies first basket, race to X, and exact score all
NOT_WIRED_WITH_REASON (tip/first-possession event data, play-by-play, and a
validated joint score distribution respectively — none wired). DK posts all
three on NBA game pages [grounded in the feasibility doc's classification of
DK markets]. The NBA secondary-prop draft (`research/nba_secondary_prop_20261020/`)
covers *player* props (3PM/STL/BLK/DD), is UNFROZEN/UNRUN, and does not touch
game props. *Needs:* possession-level event data (admitted: shufinskiy/nba_data,
base plan §3.3) plus a tip/first-possession construction and prereg.
**CBB — NO_CONSTRUCTION:** nothing on main prices CBB game props; the
season-prep contract (`research/cbb_season_prep_20261020/`) records CBB
game/half/player foundations as claimed by open PR #2350, unvalidated, and
the family's first problem is still capture identity (G6), not props. DK
posts CBB game props sparingly (featured games) [DK-general].
**MLB — PARTIAL:** NRFI/YRFI — DK's 1st-inning O/U 0.5 — is a game prop
already carried in production entries under the owner's Oct 26 labeling rule
(NRFI = Under 0.5; the label is applied by the program, DK shows none),
inside the base plan's game-lines family (DESIGN ONLY, MLB_GAME_DIST_V1).
The adjacent F5 family was harness-tested in Phase 7 and FAILED vs naive
(F5 ML Brier 0.2179 vs 0.2132, n=2,898) and is validation-gated shut
(`F5_MARKET_FAILED_VALIDATION_NOT_WIRED`) — recorded here so the extension
does not quietly resurrect it. First-to-score / race-to-X-runs / exact score:
BLOCKED in Phase 7 on the same two named gaps as football (scoring-timing
model; joint distribution with correlation). *Needs:* MLB_GAME_DIST_V1 is
itself a joint run distribution — if it ever validates, exact-score and race
markets become derivable from it; first-score needs the first-inning PBP
timing work already in-tree as research (`research/mlb_first_inning_pbp_pool_20261020/`).

## 2.2 SGP (same-game parlays)

**NO_CONSTRUCTION in every sport, and the reason is structural, not
neglect.** Repo evidence, three ways: (1) the Phase 7 matrix records
"Futures, SGPs/teasers: NOT_WIRED (long-horizon / correlation modeling out
of scope)", and the live doc repeats SGPs as NOT_WIRED for live;
(2) the football card renderer prints an "SGP legs" section whose own text
states the blocker — "Individual legs do not establish a combination's
probability" (`scripts/render_football_board_card.py`); (3) the CFB paper
lane explicitly refuses the path (`scripts/run_cfb_paper_market.py`:
"no SGP path in paper lane"). What exists is correlation *accounting*, not
correlation *pricing*: `sportsedge/card_correlation.py` collapses same-game
rows sharing a thesis into one graded position so a card cannot count one
correlated thesis as N independent positions — grading discipline, not a
joint-probability engine.
*What a construction needs, in order:* (a) each leg family validated on its
own (an SGP cannot verify before its legs' models do — a joint price built
on unvalidated legs inherits every leg's error, multiplied); (b) a
joint-distribution / correlation layer over the legs (shared game
simulation paths, not marginal multiplication — the same G10 layer that
exact-score game props need); (c) a baseline answer: DK's SGP price is a
single book quote with the correlation already priced in by the book and no
paired opposite side, so the contemporaneous-baseline leg of validation has
to be defined in the prereg (e.g. the book's SGP quote vs the model's joint
fair price, graded on CLV of the combined ticket) — no such prereg exists.
*Capture:* SGP quotes are not captured by the lane at all today; a capture
grammar for combined tickets (legs + combined price + timestamp) is new
work that only makes sense after (a).

## 2.3 Live in-play

**The honest headline: there is a live *repricing research* build, and there
is no live *betting* capability — no in-play capture, no in-play closes, no
validated live family.** `docs/live_inplay.md` (Phase 6, read for this
extension) documents research repricing IN_BUILD for **MLB/NFL/CFB game
markets only** (ML / spread / total / team total), market-blind by
construction (the live line is used only for downstream EV comparison, never
as a model input), fed by free game-state sources (StatsAPI live feed; ESPN
scoreboard situation) and by **user-supplied live lines via phone intake —
not by any DraftKings in-play capture**. Per sport:
- **MLB — PARTIAL:** live ML repricing holds a harness-replay
  CONDITIONAL_PASS (810 tick predictions over 45 completed 2025 games;
  Brier 0.1627 vs 0.2338 for the static pregame comparator) — but the
  market-baseline leg is MISSING (no archived prices for those games), so
  under current law this is one leg of a validation, not a pass. Status on
  every row: `LIVE_RESEARCH_CANDIDATE_NOT_VALIDATED`.
- **NFL / CFB — PARTIAL + NO_DATA (validation):** the repricing machinery
  exists and is unit-tested (at kickoff it reduces exactly to the pregame
  model; OT refused; fail-closed staleness at 60s), but the doc states
  plainly "NFL/CFB live repricing: CANNOT be validated yet" — ESPN does not
  retain completed-game live situation, so tick-by-tick replay is impossible
  from free sources. CFB additionally prices under an explicit
  participation-assumed flag (no free in-game participation source).
- **NBA / CBB / NHL / PGA-live-as-extension / UFC / DWCS:** the Phase 6
  build does not cover basketball or hockey at all (NO_CONSTRUCTION +
  NO_DATA). PGA's live module (§1C) is a separate in-tournament simulation,
  not part of Phase 6. MMA has card-input tooling only.
- **Live splits and live props are blocked even where live game lines
  exist:** 1H/2H/quarter splits `LIVE_SPLIT_UNMODELED`; live player props
  NOT_WIRED in all three built sports; live NRFI/1st-inning derivatives
  deferred. Alt lines are priceable by the same machinery but NOT_WIRED
  until primary lines validate.
*What live needs before any family can validate:* (1) an **in-play capture
scope that does not exist** — timestamped in-play DK quotes at defined game
states; the pregame T-1H/FINAL lane cannot produce them and must not be
stretched into pretending it did; (2) archived in-play game state to replay
against (the NFL/CFB blocker above); (3) a latency discipline — the build's
own constants (30s poll cadence, 60s fail-closed staleness) define the
freshness a capture would have to meet; (4) preregs per family that define
the baseline (the in-play close at a stated game state) before any forward
accrual. Until (1) exists, every live line in this grid is capped at
PARTIAL, and most are NO_CONSTRUCTION.

## 2.4 NHL detail

The NHL stack on main is a *capability boundary*, not a pricing engine:
`sportsedge/sports/nhl/market_capabilities.py` registers 15 markets
(ML, puck line, total, both team totals, regulation ML, period ML/total,
player shots/points/goals/assists, goalie saves, player blocks, player
hits), every one at status `REQUIRES_ENGINE` with the PIT state it demands
(shared goal paths, goalie state, PIT player role, same-path player event
distributions); unregistered markets return `NO_ENGINE`. The one live
construction leg is game lines: `NHL_PUBLIC_BOXSCORE_BASELINE_V1`, an
official-boxscore ridge baseline whose validation prereg
(`config/research/nhl_public_baseline_validation_prereg_v1.json`) is
FROZEN_BEFORE_IMPLEMENTATION — and whose own validation window is labeled
`REUSED_RETROSPECTIVE_DEVELOPMENT_HOLDOUT_NOT_FORWARD_BETTING_EVIDENCE`,
with retroactive PIT claims forbidden. That is exactly a PARTIAL: a real
construction, a frozen research validation, and an explicit statement that
the evidence is developmental, not forward. Capture-side, the NHL issue
template prices game lines and states goal/point/assist props are
`NO_MODEL` on purpose — consistent with the NO_CONSTRUCTION player-prop
rows. *Needs:* the baseline validation run to completion under its prereg;
the shared goal-path engine state the capability contract demands (which
then mechanically unlocks team totals and, with period paths, period
lines); PIT player-role/lineup state (the NHL analogue of G3's identity
problem) before any player-prop family can be designed. Performance data
is not the gap (official boxscore/PBP collectors are in-tree:
`scripts/collect_nhl_official_boxscores.py`, `sportsedge/sports/nhl/official_pbp_source.py`).

## 2.5 PGA / UFC / DWCS detail

**PGA.** Inputs the engine already assumes: full-field entries, tee
times/waves, course and weather state, leaderboard state (live), and paired
or complete-field market quotes bound per family. The benchmark contract
(`config/pga_benchmark_methodology.json`) is frozen *before* any predictive
evidence exists — deliberately: "No historical evidence collected under a
different market-shape methodology can be used for promotion without an
explicit versioned migration/re-run." *Needs:* a point-in-time evidence
program per family (the owner's scoping names DataGolf / OWGR / PGA Tour
stats as the data side — none admitted yet in-repo), a DK capture grammar
for golf's weekly cadence (the T-1H/FINAL per-game lane shape does not map
to a 4-day tournament; pre-tournament and per-round capture points must be
defined in a prereg), and settlement verification (dead heats, WD rules)
which the status doc lists as invariants, not results. DataGolf's
historical odds archive, if admitted, would be design data by the standing
rule (any vendor archive the program did not capture live is not a
contemporaneous DK baseline).
**UFC.** Inputs named by the surface contract: a fighter snapshot per bout
(`fighter_snapshot_required`) and paired prices. The design doc
(`docs/ufc_model_design.md`) requires chronological OOS validation before
ensembling and an untouched holdout before promotion. *Needs:* automated
model inputs (today `automatic_model_inputs: false`), a fight-history
substrate admission (owner scoping names ufcstats.com and Kaggle fight
history — neither admitted yet in-repo), DK capture for UFC cards (event
cadence, not per-game), and — for method/round families — a genuinely new
engine: finish-type and round distributions are a different model than a
win-probability sim, which is why the surface refuses them rather than
approximating them.
**DWCS.** Everything UFC needs, plus the thin-data problem as the binding
constraint: a weekly card of near-debutants means the fighter-snapshot
requirement often cannot be met with real history. The honest construction
consequence: bouts without admissible history must price as uncertainty
(wide intervals / no-model rows), never with imputed certainty — the repo's
card note already states this. Event-specific validation is required by the
surface contract before any DWCS line can move; a UFC-level verdict does
not transfer to DWCS by inheritance.

---

# 3. DEPENDENCY ORDER — which families unblock which

Read top-down; nothing lower on the list can verify before the things above
it. (Within a level, the owner's priority order — NFL → CFB → NBA → CBB →
MLB, NHL re-entered, new sports scoped — still governs sequencing effort.)

1. **Legs first.** Per sport: sides, totals, team totals, player props.
   These are the base plan's 26 lines and they gate everything below. An
   SGP whose legs are unvalidated is unvalidatable; a live model is an
   adaptation of a pregame model (`docs/live_inplay.md`: at kickoff the
   live repricing is exactly the pregame model — a broken pregame model
   makes a broken live model at every tick).
2. **Joint-distribution / correlation layer (G10).** One shared-path game
   simulation per sport unlocks, together: exact-score game props, SGP
   pricing, and honest margin-band refinement. This is a single build per
   sport, not three. MLB is closest (MLB_GAME_DIST_V1 is a joint
   distribution by design); football is furthest (normal marginals, no
   joint); basketball has possession data admitted but no joint
   construction.
3. **Scoring-timing distributions.** PBP-derived first-score / race-to-X /
   first-TD constructions (G9) — independent of level 2, blocked on
   timing-distribution design + prereg, not on data availability for
   NFL/MLB/NBA.
4. **Pregame → live.** Live adaptations only after the pregame family
   validates, AND after the in-play capture scope (G8) exists: capture is
   the precondition, the pregame model is the engine, archived in-play
   state is the replay substrate. NHL/PGA/UFC/DWCS live all sit behind
   their pregame families *and* behind G8.
5. **New-sport main families → new-sport derivatives.** PGA outrights /
   top-K / H2H evidence before PGA round props can mean anything; UFC
   moneyline (automated inputs + holdout) before method/round engines are
   designed; DWCS behind UFC's surface *and* behind its own event-specific
   validation — never inherited.
6. **NHL internal order.** Public-baseline validation (frozen prereg) →
   shared goal-path engine state → game lines unlock team totals →
   period paths unlock period lines → PIT player-role state unlocks
   player props. Game props and SGP sit at NHL's levels 2–3 equivalents.

# 4. NEW GAPS INTRODUCED BY THIS EXTENSION

- **G8 — In-play capture and in-play closes (all sports).** No in-play
  capture scope exists; the lane is pregame T-1H/FINAL by owner rule.
  Without timestamped in-play DK quotes at defined game states there is no
  contemporaneous baseline for any live family, and for NFL/CFB there is
  not even an archived in-game *state* record to replay against. This is
  the live analogue of G1/G2/G4/G5 combined, and it is a scope decision
  (new lane work), not a dataset purchase.
- **G9 — Scoring-timing distributions.** First-score, race-to-X, and
  first-TD families in NFL/CFB/MLB (and first-basket in NBA) need
  P(team/player reaches the mark first) distributions. Performance PBP
  exists; the timing constructions do not.
- **G10 — Joint-distribution / correlation layer.** SGP and exact-score
  pricing program-wide. Card-level correlation accounting exists
  (`sportsedge/card_correlation.py`); price formation does not.
- **G11 — New-sport odds and evidence archives.** No DK odds history for
  PGA/UFC/DWCS is in-tree; no performance substrate is admitted yet for PGA
  (DataGolf/OWGR/Tour stats) or MMA (ufcstats.com/Kaggle). DWCS adds a
  structural NO_DATA: many fighters have little or no pro history anywhere.
- **G12 — NHL PIT player-role state.** Lineup/TOI/power-play role as of
  puck drop, timestamped — required by every NHL player-prop capability
  registration; the NHL analogue of G3.

# 5. UPDATED HEADLINE COUNTS

Base plan: 26 lines, VERIFIED 0. This extension adds **40 lines**:
15 (three new families × five Phase 1 sports) + 8 NHL + 7 PGA + 5 UFC +
5 DWCS. Program total: **66 market-family lines, VERIFIED 0.**

Extension-line status tally, counted from the §1 grids: **PARTIAL 16**
(NFL/CFB/MLB game props; NFL/CFB/MLB live; NHL game lines and team totals;
PGA outrights, top-K, H2H, make-cut, round props, live; UFC moneyline;
DWCS moneyline) · **NO_CONSTRUCTION 19** · **NO_CONSTRUCTION + NO_DATA 5**
(NBA live, CBB live, NHL live, UFC live, DWCS live). Three PARTIAL lines
carry NO_DATA as a co-binding constraint, stated in their grid rows: NFL
and CFB live (validation substrate) and DWCS moneyline (per-fighter
history).

*End of taxonomy extension. No engine code was written, no dataset was
admitted, and no clock, count, or verification claim is made by this
document.*
