# Forward-Validation Program — program map and capture-scope gap map

**Status: PROGRAM MAP, Oct 20, 2026.** Prepared under the owner's directive
"keep building to point everything is validated" (Oct 20, 2026), extending
the build-all-engines directive of the same day. Branch
`feat/forward-validation-program-20261020` on `b834101f9` (main `07b46d383`
+ CFB research registration). Everything in this document is state as
verified from the repository and the NO_ENGINE inventory
(`~/workspace/sportsedge/no_engine_inventory_20261020/INVENTORY.md`,
Oct 20, 2026); in-flight branches are recorded as **state-known, not
merged**.

## 1. The standing law (not restated law — the operating rules)

A family validates ONLY through a preregistered forward test scored
against our own timestamped DraftKings captures. CLV vs the final
pre-event capture is the primary verdict metric; calibration and
win/loss are secondary. Confidence intervals are clustered by game.
A market under its row/game minimums is `INSUFFICIENT_SAMPLE`, never a
verdict. If more than 20% of a market's rows lack a readable close, the
verdict is `INSUFFICIENT_CLOSE_DATA`. Every model version is scored AS
IT STOOD when it priced the games; a changed construction is a new
version on a new clock. Historical screens and calibration runs are
entry tickets, never validation. **No verdict creates a PLAY** — PLAY
stays closed until the owner rules on a completed verdict. Validated
families today: **zero**, in every sport.

**Frozen tests already in force are separate instruments.** This
program does not modify, duplicate, or re-preregister any of them:
NFL props Part 2 (PR #2396, frozen Oct 18), NFL props Part 2B
(PR #2415, frozen Oct 20 — in force on its branch, counts Thursday
Oct 22 only if merged before Thursday pricing), the anytime-TD forward
test (locked Oct 18, PR #2399), the NFL totals LEVEL v2 forward leg
(screen-passed successor construction; forward leg scores Jan 13,
2027), and the MLB pitcher-prop promotion preregistration
(`docs/MLB_PITCHER_PROP_PROMOTION_PREREG.md`, v2, Oct 4, 2026).

## 2. What this program adds

1. **A universal evaluator framework** — `sportsedge/forward_validation/`:
   a family is declared by a JSON config (sport, family, market keys,
   the frozen model-version string, market form, minimum rows/events/
   slates, the close window) and the evaluator consumes priced records
   + close captures + outcomes and emits the standard verdict record
   (`BEATS_MARKET` / `DOES_NOT_BEAT_MARKET` / `INSUFFICIENT_SAMPLE` /
   `INSUFFICIENT_CLOSE_DATA`) with CLV, calibration deciles, and
   game-clustered CIs. Its statistics are the frozen Part 2 mechanics,
   copied verbatim with attribution (the pinned evaluator's `boot`;
   the Part 2 pricer's multiplicative de-vig) and parity-tested against
   the pinned files. It refuses, fail-closed with a named reason, to
   score: rows priced by a different model version than the config's
   frozen version (`MODEL_VERSION_MISMATCH`); records written after
   their event started that are not labeled HISTORICAL
   (`POST_START_RECORD`; HISTORICAL records are excluded from verdict
   math, only counted); records or closes lacking timestamps
   (`RECORD_MISSING_TIMESTAMP`, `CLOSE_RECORD_MISSING_TIMESTAMP`);
   duplicate prospective rows; invalid probabilities or prices. Close
   violations are per-row `CLV_MISSING` with the five frozen reasons —
   never backfilled.
2. **DRAFT preregistrations** for every family with a working engine
   that no frozen test covers — 35 drafts in `drafts/` beside this
   map, each with its framework config in
   `sportsedge/forward_validation/configs/`. Every draft is marked
   **DRAFT — NOT FROZEN, NOT IN FORCE**. Freezing is the owner's act,
   per family; no game counts before its freeze.
3. **This map**: every family's current state and its exact blocker
   to a verdict, including the capture-scope gaps (Section 5) and the
   families with no DraftKings market to test against (Section 6).

## 3. How a family reaches a verdict (the pipeline, for reference)

`engine → wiring (priced records on the canonical path) → registration
(state that permits research pricing) → draft preregistration → owner
freeze → prospective rows accrue from paired DK captures → gates met →
verdict`. A family can be blocked at any step; Section 4 names the
blocking step for each family. Building an engine, writing a draft, or
even freezing a preregistration changes no family's eligibility by
itself.

## 4. Family map

State vocabulary: engine = WIRED / EXISTS_UNWIRED / NO_ENGINE / CLOSED
(per the inventory); test = FROZEN (in force) / DRAFT (written here) /
COVERED-SIBLING / NONE, with the blocker to a verdict stated exactly.

### 4.1 MLB (55 families)

**Draft preregistration written (19 drafts covering 20 wired families).
Blocker to a verdict for each: owner freeze, then prospective rows
from the operative paired DK capture per game.**

| Family | Engine | Notes on the record |
|---|---|---|
| MONEYLINE, RUN_LINE, TOTALS, TEAM_TOTALS | WIRED (FREE_MODELS_GAME) | Lane A prior verdict disclosed in each draft: the construction was retired as a card-source engine after a historical DOES_NOT_BEAT_MARKET (Brier 0.247856 vs market 0.236332, n=10,237). The drafts bind the as-it-stands construction on a fresh forward clock; leaving them unfrozen is a legitimate owner disposition. |
| FIRST_INNING_RUN (NRFI + YRFI) | WIRED (MLB_FIRST_INNING_BINARY) | The inventory names NRFI and YRFI as two families; they are the two sides of one two-sided DK market, declared here as one family over that market. |
| HITS, TOTAL_BASES, RBI, RUNS, BATTER_BB, SINGLES, DOUBLES, HITS_RUNS_RBIS, HOME_RUNS, BATTER_K, TRIPLES, EXTRA_BASE_HITS, RUNS_RBIS (13) | WIRED (MLB_BATTER_EMPIRICAL_GAMELOG) | Negative calibration verdicts (DOES_NOT_BEAT_BASELINE) on record — disclosed in each draft; calibration record, not closure. Priced rows exist only behind the engine's fail-closed gates (≥10 prior games, ≥20 PA, verified starting lineup). |
| PITCHER_OUTS | WIRED (MLB_PITCHER_JOINT_EMPIRICAL_BAYES) | Not in the promotion study's market set — takes the standard draft. |

**Covered by a committed preregistration — NOT drafted here (no
duplicate instruments):**

| Family | Covering instrument | Path to verdict |
|---|---|---|
| PITCHER_K, PITCHER_BB, PITCHER_ER, PITCHER_HITS_ALLOWED | `docs/MLB_PITCHER_PROP_PROMOTION_PREREG.md` (v2, Oct 4, 2026) | One-shot study over the archived 2026 PIT quote archive (≥150 graded units, ≥40 flagged bets), run once after the 2026 postseason. Its design predates the CLV-primary standard (it scores model_p vs the de-vigged price plus flagged-bet ROI, with no CLV leg) — recorded as state-known; altering it is an owner act, not this program's. The card-side pitcher-K unit ledger is an operative record, not a validation instrument. |

**Verdict already on record — CLOSED (11). No forward test; a return
requires a new construction version and a new preregistration:**
EITHER_PITCHER_HITS_ALLOWED / _BB / _ER (DOES_NOT_BEAT_BASELINE,
pricing refused), PITCHER_PITCHES (DOES_NOT_BEAT_BASELINE, M29;
registered RESEARCH_ONLY, promotable:false), run-line alternates
(DOES_NOT_BEAT_BASELINE), total-runs alternates (harness FAIL vs
naive), moneyline 3-way 9-inning (harness FAILED vs naive), game total
hits and team total hits (DOES_NOT_PASS, frozen scoring), 1st-inning
team runs and team hits (harness fail / not robust).

**Engine exists, not wired — blocker named (11):**

| Family | Blocker to a verdict |
|---|---|
| F5_MONEYLINE, F5_RUN_LINE, F5_TOTALS, F5_TEAM_TOTALS | Engine complete; the only gate is the deployment ruling (`eligible=false`, F5_STATE_CANDIDATE). No priced records can exist until the owner rules eligibility; a draft follows immediately once rows can be priced. |
| STOLEN_BASES | The wired batter engine prices the stat in research; the blocker is per-fixture quote evidence (not observed on the inspected fixture). Once SB lines are verified on a DK board, this family joins the batter draft set unchanged (same engine, same gates). |
| HITS_RUNS_STOLEN_BASES, HITS_STOLEN_BASES, HITS_WALKS_STOLEN_BASES | Joint engine exists behind the manual-snapshot intake contract; blocker = the canonical intake binding build. |
| PITCHER_HITS_WALKS_ER | Engine exists; the market was verified absent at DK (M30) → **NO_MARKET_TEST_EXISTS** unless a DK offering appears. |
| PITCHER_RECORD_WIN | Candidate v2 exists (research only); its own gates (PIT, holdout, calibration, settlement, parity) are all unsatisfied per the module itself, and the offering is unverified on the enumerated board. |
| FIRST_HOME_RUN | Candidate exists; blocker = the N-way multi-outcome selection-set binding (the canonical path binds binary/pair/partition only) plus PBP first-HR settlement attribution and offering evidence. |

**NO_ENGINE — greenfield (9):** total runs 3-way; F5 both-teams-to-score
ladder; F5 winning margin / correct score; 1st-3-innings set;
1st-7-innings set; 1st-inning deep set; per-inning 2nd–9th sets; plate
appearance markets (M49 — the exception: a calibrated construction
EXISTS, BEATS_BASELINE at construction level over 152,053 PAs, but no
engine module exists and the PBP pool it needs sits only on the
unmerged branch `research/mlb-pbp-pool-20261016`; the pool landing is
the first blocker); game exotics set. For all nine the blocker chain
is: engine build → (registration where applicable) → draft → freeze →
captures.

### 4.2 NFL (51 families)

**FROZEN — in force (no action in this program):**

| Family | Instrument | Status |
|---|---|---|
| PASSING_YARDS (passing_yards), RUSHING_YARDS (incl. its rush_yards alias spelling), RECEIVING_YARDS, RECEPTIONS | Part 2 forward test, PR #2396 (frozen Oct 18) | Prospective count opens with the first slate priced from the committed package: TNF Thu Oct 22, 2026 (Patriots @ Bears). Gates: 4 full slates + 50 passing-yards rows + 40 distinct games per market; ≥100 graded rows per market; CLV primary. |
| RUSH_ATTEMPTS, PASS_ATTEMPTS (attempts), COMPLETIONS | Part 2B forward test, PR #2415 (frozen Oct 20, §6 ruled option (a)) | In force on its branch; Thursday's rows count ONLY if the package is on main before Thursday pricing. PASSING_TDS is SHADOW-ONLY under 2B: priced and recorded, never counted toward any verdict. |
| ANYTIME_TD | Locked forward test, PR #2399 (`docs/football/NFL_ANYTIME_TD_FORWARD_TEST_V1.md`) | Engine v1 on branch `feat/nfl-atd-engine-v1-20261018` (state-known, not merged); first counted week opens Thu Oct 22. 4 full weeks, ≥150 picked rows, ≥40 games. |
| TOTAL (LEVEL v2 construction) | LEVEL v2 forward leg (research branch `research/nfl-totals-level-v2-20261017`) | Historical SCREEN_PASSED vs climatology baseline B2; forward leg on games from Oct 18, 2026, scores Jan 13, 2027. This is the designated successor path for NFL totals and is untouched here. |

**Draft preregistration written (13 drafts). Blocker to a verdict for
each: owner freeze, then rows (capture conditions per family):**

| Family | Engine | Capture / market condition |
|---|---|---|
| MONEYLINE, SPREAD | WIRED (FREE_MODELS_GAME) | In Capture Spec V1's per-game subset (entry + close). Drafts disclose the #2384 WATCH hold (a card-label hold) and that the Elo v1 / challenger verdicts closed different constructions. |
| TOTAL (free_models construction) | WIRED (FREE_MODELS_GAME) | In spec. The draft binds the card construction (WATCH_NFL_TOTAL_PRIOR_ONLY) and states it must never be conflated with LEVEL v2's clock; the owner may legitimately leave it unfrozen and let LEVEL v2 be the totals path. |
| PASS_PLUS_RUSH_YARDS | BUILT (NFL_PROP_ENGINES_V1 @ 8b2775008) | Screen CALIBRATED_CANDIDATE. Capture expansion required (not in the spec subset). |
| RUSH_PLUS_REC_YARDS | BUILT (NFL_PROP_ENGINES_V1) | Screen CALIBRATED_CANDIDATE. Capture expansion required. |
| TARGETS | BUILT (NFL_PROP_ENGINES_V1) | Screen CALIBRATED_CANDIDATE — but the market is verified ABSENT at DK (N55): zero rows can accumulate → **NO_MARKET_TEST_EXISTS** unless DK lists targets or another book's captures are owner-authorized as the price source. The draft is written so the test exists the day a market does. |
| TWO_PLUS_TD | BUILT (NFL_PROP_ENGINES_V1) | Screen DOES_NOT_BEAT_BASELINE (disclosed in full in the draft). YES_ONLY form; capture expansion = add the 2+ TD Yes board to the per-game subset. |
| FG_MADE, XP_MADE, KICKING_POINTS | BUILT (NFL_PROP_ENGINES_V1) | Screen not runnable on the sanctioned vintage (kicking columns exist only in sp_2025); 2025-only diagnostics recorded in each draft (XP beats both baselines diagnostically; FG ties B2; kicking points straddles zero vs B2). Capture expansion required. |
| PLAYER_SACKS, TACKLES_ASSISTS, PLAYER_INTERCEPTIONS (all defensive) | BUILT (NFL_PROP_ENGINES_V1) | Screen not runnable on the vintage; diagnostics in each draft (tackles beats both; sacks ties B1 / beats B2; player interceptions LOSES to the pool baseline — near-noise at game-log resolution, disclosed). Defensive player props were verified absent at DK in the Oct 17 samples (N54): rows accumulate only in weeks DK actually lists them → **NO_MARKET_TEST_EXISTS on current evidence**. **Naming discipline:** PLAYER_INTERCEPTIONS (defensive interceptions, drafted here) is a different family from INTERCEPTIONS (QB thrown, below). |

**Blocked before any draft can operate:**

| Family | Blocker to a verdict |
|---|---|
| INTERCEPTIONS (QB thrown) | Explicitly OUT of Part 2B scope by owner ruling (the pricer refuses it, `MARKET_OUT_OF_SCOPE_2B`). The shared empirical pricer exists, but a forward test requires a new owner ruling bringing the family into scope; no draft is written against a scope exclusion. |
| FIRST_TD | NO_DATA, not NO_ENGINE: no verified first-scoring attribution source exists (`NO_VERIFIED_FIRST_SCORING_ATTRIBUTION`). Data first, engine second; no verdict path until an attribution source is verified. |
| TEAM_TOTAL; FIRST_HALF / SECOND_HALF / QUARTER moneyline, spread, total (9); ALTERNATE_SPREAD, ALTERNATE_TOTAL | Derivative pricers exist and are wired as derivatives, but their required input — an independent joint score distribution on the canonical path — does not exist (the canonical path is analytic). Alt lines and team totals additionally sit under the G2 Attempt 2 hold (NO-GO, unspent). No priced records can exist until the input is admitted; drafts follow that admission. |
| LONGEST_COMPLETION, LONGEST_RUSH, LONGEST_RECEPTION | A PBP empirical engine exists (governance-unadmitted). The Oct 20 engines build deliberately did NOT rebuild these from game logs: no per-game longest-play outcome exists in the sanctioned snapshot (logs carry sums/counts, never a maximum), so a game-log engine would fabricate its outcome. Blocker = a data decision (admit a PBP-derived per-game longest panel) plus governance admission. |
| RACE_TO_N_POINTS, FIRST_SCORE, LARGEST_LEAD, WINNING_MARGIN_BAND, BOTH_TEAMS_TO_SCORE_N, TOTAL_TOUCHDOWNS, LONGEST_FG_MADE, DEFENSIVE_SPECIAL_TEAMS_TD, SAFETY (9) | NO_ENGINE — catalog declarations only ("no pricing engine for this market exists anywhere in the repository"). Most are score-path derivatives that would fall out of a joint score distribution if one is ever admitted; the unmerged joint-score factory is NOT a usable basis as-is (known defect: simulated mean total 15.92 vs a real ≈46). Blocker chain: engine build → admission → draft → freeze → captures. |

### 4.3 CFB (49 families)

**Draft preregistration written (3): MONEYLINE, SPREAD, TOTAL.**
Registration is done (owner Option B, PR #2416 —
REGISTERED_RESEARCH_ONLY / NOT_VALIDATED, research pricing only when
Form 2 identity is satisfied for both teams; PLAY impossible). The
engine (FREE_MODELS_GAME) prices all three today. **Blockers to a
verdict, in order:** (1) the runner-wiring build (branch
`feat/cfb-runner-wiring-20261020`, in flight) must land and merge so
identity-satisfied fixtures produce priced records end-to-end;
(2) the capture expansion in Section 5 (Capture Spec V1 has no CFB
section — the Oct 20 CFB reads were price records only and can never
enter a test); (3) owner freeze of each draft. The CFB evaluation HOLD
(Attempt 1 unspent) is a separate instrument and is untouched by
registration, by these drafts, and by any freeze of them.

**Blocked before any draft can operate:**

| Family | Blocker to a verdict |
|---|---|
| TEAM_TOTAL | Registration: Option B deliberately kept CFB team totals BLOCKED. Construction: surface-declared IMPLEMENTED but the canonical phone engine refuses it (`UNSUPPORTED_MARKET_NO_PROP_MODEL`) and no team-total construction has ever been scored (forward-only family: no corpus carries historical team-total lines). Chain: construction build/reconciliation → owner registration ruling → draft → freeze → captures. |
| 11 player families (passing yards/TDs/attempts/completions/interceptions-thrown, rushing yards/attempts, receiving yards, receptions, rush+rec, pass+rush) | An empirical pricer exists (the shared football bridge over ESPN gamelogs), but registration: Option B kept CFB player props BLOCKED — an owner registration ruling is required before research pricing may exist, ahead of any draft. Record note: the C10 QB passing-yards CANDIDATE returned DOES_NOT_BEAT_BASELINE (2025, n=644) — that candidate is closed; the family is not. No PIT participation/snap source exists for CFB; availability stays UNVERIFIED context. |
| 34 unregistered families (alternates ×2, period lines ×6, team-total TDs, TD scorers ×6, longest ×3, kicking ×3, defensive ×5, game exotics ×8) | NO_ENGINE and unregistered (FAMILY_MARKET_UNREGISTERED). Chain per family: engine build → owner registration ruling → draft → freeze → captures. No participation model exists for CFB at all, which additionally gates the TD-scorer group. |

### 4.4 NBA (19 readiness rows)

**Covered by sibling — NOT duplicated here (4):** player POINTS,
REBOUNDS, ASSISTS, and the PRA combo. The sibling build (branch
`feat/nba-prop-engines-20261020`, in flight) is parity-reproducing the
frozen Oct 17 calibration construction (BEATS_BASELINE on the ESPN
snapshot, n=16,818: PTS CRPS 3.5653 vs 4.9724; REB 1.4413 vs 1.7707;
AST 1.0055 vs 1.3678; PRA 4.7082 vs 6.9463), wiring the engines,
registering the four families research-only, and writing the draft
preregistration (`PREREG_NBA_PROPS_FORWARD_V1_DRAFT`, DRAFT — not
frozen). DK captures for these families are already in Capture Spec
V1's NBA scope and accrue twice daily. This program's map entry is
the complete record; the draft itself lives with the sibling build.

**Blocked before any draft can operate (the rest of the NBA board):**

| Family | State and exact blocker to a verdict |
|---|---|
| MONEYLINE, SPREAD, GAME TOTAL | Raw ratings model exists and is pinned; verdict record **FAILED_VALIDATION** — an accuracy gap vs the close on all three (moneyline Brier diff +0.0117 [0.0087, 0.0147]; spread RMSE 13.83 vs line 13.30; total RMSE 21.46 vs 20.72; untimestamped odds vintage, so an accuracy-gap verdict, not a beat-the-close verdict). The shipped model's totals copy the DK line and are untestable by construction; the owner-decided test subject is the RAW model. Chain: any successor is a NEW version under the version-scoring rule, scored forward only → registration ruling (families currently resolve BLOCKED / NO_VALIDATION) → draft → freeze. Captures already accrue (twice-daily job). The totals-bias diagnosis (NO_BIAS vs reality; BIAS_UNSTABLE vs close; defect is dispersion, no totals v2 proposed) is context for the successor's design, not a fix to apply silently. |
| TEAM TOTALS | Ratings construction exists; calibration BEATS_BASELINE vs climatology (MAE 8.9975 vs 9.5411, n=15,506). No market test has ever existed (the historical odds source had no team-total column). DK captures now accrue team totals (first captured Oct 19 PM). Chain: wiring + registration ruling → draft → freeze. |
| PERIOD MARKETS (quarter / half totals and lines) | Period machinery exists; quarter totals calibration BEATS_BASELINE vs climatology (MAE 4.6103 vs 4.7070, n=62,024). Blocker: period LINES are in no capture scope — capture expansion precedes everything else. |
| Other two-stat combos (PTS+REB, PTS+AST, REB+AST) | PRA-style construction exists (derived sums modeled directly), not separately scored as families. Chain: wiring (with the sibling's build pattern) + registration → draft → freeze. DK capture scope covers "common combination props" — which combos are actually listed is a per-slate fact to record at capture. |
| THREES, STEALS, BLOCKS, TURNOVERS | Backtest-lane construction exists; calibration BEATS_BASELINE on the Oct 17 snapshot (all n=16,818). Two build blockers precede any test: the maintained results pull emits only PTS/REB/AST/MIN (these stats' outcomes have no maintained source), and their lines are not in DK capture scope. |
| DOUBLE-DOUBLE | Research construction exists (declared Bernoulli adaptation); calibration BEATS_BASELINE (Brier 0.0708 vs 0.0926). Lines not in capture scope. |
| Alternate spread/total ladders; winning-margin / correct-score exotics; TRIPLE-DOUBLE; FIRST BASKET / race-to | NO_ENGINE (greenfield). First basket additionally has no data path in hand (no verified first-score attribution source) — data-first, like NFL first TD. |

### 4.5 CBB (3 named families)

MONEYLINE, SPREAD, TOTAL: **NO_ENGINE** — no CBB engine code exists
anywhere in the tree. Registration resolves BLOCKED / NO_VALIDATION.
The capture program is specified to begin by Nov 1, 2026 (complete
game-line board first, per Capture Spec V1) — captures precede any
engine by design. Chain: captures accrue → engine build (greenfield;
the NBA ratings construction is a different sport's model and is not a
substitute) → registration ruling → draft → freeze. All other CBB
markets are unregistered NO_ENGINE and unnamed in any registry.

### 4.6 Parked sports

NHL, UFC, PGA are parked by owner ruling (NHL reaffirmed parked
Oct 20, 2026, after its backtest returned NO EDGE with the earlier
positive result shown to be look-ahead leakage). They are outside
this program until the owner unparks them.

## 5. Capture-scope gap map

The verdict currency is paired, timestamped DraftKings captures:
an ENTRY capture before event start and a CLOSE capture that is the
last capture before start and ≤60 minutes before it. What the capture
program covers today (Capture Spec V1, on main via PR #2403, plus the
operative RUN IT capture flow) vs what the tests require:

| Scope | Covered today | Gap and the exact expansion required |
|---|---|---|
| NFL — Thursday full board (NE@CHI, Oct 22) | Full available board, entry + close (spec) | None for that game. This is the proof capture for Part 2 / 2B / anytime-TD. |
| NFL — every other game | Predeclared subset: the four Part 2 prop markets, the anytime-TD Yes board, main game lines (spec) | The ten new-engine families are NOT in the subset. Expansion (spec amendment, owner-ruled): add PASS_PLUS_RUSH_YARDS, RUSH_PLUS_REC_YARDS, FG_MADE, XP_MADE, KICKING_POINTS paired lines and the TWO_PLUS_TD Yes board to the per-game subset. TARGETS and the defensive families need no expansion — they need a market to exist (Section 6). Part 2B's markets (rush attempts, pass attempts, completions, shadow passing TDs) ride the Part 2B package's own capture terms. |
| NFL — team totals, periods, alternates | Not covered | Moot until the joint-sim input is admitted (Section 4.2); capture design follows that admission, not before. |
| CFB | **Nothing.** Capture Spec V1 has no CFB section; the Oct 20 reads were single price records with no close, usable as context only | Expansion required before any CFB row can count: a CFB section in the capture spec — game lines (moneyline, spread, total, both sides) with paired ENTRY + CLOSE captures per game under the spec's timing rules, following the pattern the spec sets for CBB, plus the Form 2 identity record for both teams attached to each priced fixture. Illinois-excluded and Tennessee-blocked fixtures are never captured for pricing. |
| NBA | Game lines + PTS/REB/AST + common combos, twice daily (AM/PM jobs live since Oct 19; team totals captured from Oct 19 PM) | Period lines (quarter/half) are not captured — expansion required before any period test can be drafted. THREES/STL/BLK/TOV lines are not captured, and their outcomes lack a maintained results pull — both are build decisions ahead of capture design. Which "common combos" DK lists beyond PRA is a per-slate fact the capture must record verbatim. |
| CBB | Specified, not yet started: complete game-line board first, then player props; live by Nov 1, 2026 | On schedule per spec; no engine exists to test yet, so no test-side gap. |
| MLB | Operative paired capture per RUN IT game (entry before first pitch; close per the framework's close rule at first pitch) | No standing twice-daily MLB capture job exists; MLB tests accrue rows only on games actually run through the operative flow. That is a throughput fact, stated plainly: at current cadence the 150-row gates are a season-scale accumulation for most MLB families. A standing MLB capture job (full daily board, entry + close) is the expansion that changes it — an owner scope decision, since it widens the capture program beyond Capture Spec V1's sports. |
| NHL / UFC / PGA | NHL price records only (parked) | None — parked sports are out of the program. |

**Close-window discipline is uniform** (framework config
`close_max_age_minutes: 60` everywhere, the Capture Spec rule): a
close at exactly 60:00 before start is readable; 60:01 is
`CLOSE_STALE`. Entry captures have no earliest bound, but an entry at
or after event start is excluded per row, and a priced record written
after its event started is historical by definition.

## 6. Families with no market to test against (NO_MARKET_TEST_EXISTS)

A forward test needs a book's prices. These families terminate at
**NO_MARKET_TEST_EXISTS** — a terminal state, not a pending one —
unless a market source appears (DraftKings lists the market, or the
owner authorizes another book's captures as the family's price
source, which would itself require a preregistration naming that
source):

| Family | Evidence |
|---|---|
| NFL TARGETS | Verified absent at DK (Oct 17 matrix, N55). Draft written (Section 4.2) so the test exists the day a market does; zero rows can accrue meanwhile. |
| NFL PLAYER_SACKS, TACKLES_ASSISTS, PLAYER_INTERCEPTIONS (defensive) | Verified absent at DK in the Oct 17 matrix samples (N54). Drafts written; rows accrue only in weeks DK actually lists them. If DK lists them intermittently, the tests remain valid but accumulate at the market's cadence, and every readout must state the listing gaps. |
| MLB PITCHER_HITS_WALKS_ER | Market verified absent at DK (M30). Engine exists; no draft — the instrument is pointless until an offering exists, at which point it joins the pitcher draft set. |
| CFB kicking and defensive groups (inside the 34 unregistered) | No kicking markets on the sampled board (M16); defensive market class absent at DK in verified samples (M17). Both groups are also NO_ENGINE + unregistered, so the market absence is one of two independent blockers. |

Distinct from NO_MARKET: **NFL FIRST_TD and NBA FIRST BASKET** are
data-blocked, not market-blocked — DK offers first-scorer markets,
but no verified first-scoring attribution source exists on our side
to settle or price against. Their terminal state until a source is
verified is NO_DATA.

## 7. In-flight branches register (state-known, NOT merged)

| Branch / PR | What it carries | Why this program cares |
|---|---|---|
| PR #2416 — `feat/cfb-research-registration-20261020` @ `b9c26559e` | CFB Option B registration | The drafts in this program for CFB are parented on its local commit `b834101f9`; they assume the registration lands as built. If it changes, the CFB drafts' Section 1 text must be re-checked at freeze. |
| PR #2415 — `feat/nfl-props-part2b-freeze-20261020` @ `8813ea5a0` (remote) | Part 2B freeze (doc + evaluator + code) | Frozen test; Thursday counting depends on its merge timing. Not duplicated here. |
| `feat/cfb-runner-wiring-20261020` | CFB runner wiring on top of the registration commit | Blocker (1) for the CFB drafts' verdict path (Section 4.3). |
| `feat/nba-prop-engines-20261020` | NBA PTS/REB/AST/PRA engines + registration + sibling draft prereg | The four NBA prop families are covered there (Section 4.4). |
| `feat/nfl-prop-engines-20261020` @ `8b2775008` | The ten new NFL prop engines + screens | The engine build every NFL prop draft in this program binds (`model_version: nfl_prop_engines_v1@8b2775008`). If the branch's head moves before it merges, the version string in those configs must be re-pinned at freeze to the merged build that actually prices — the evaluator's version refusal makes a stale pin fail closed rather than silently score the wrong build. |
| `feat/nfl-atd-engine-v1-20261018` @ `cae825534` | Anytime-TD engine v1 | Feeds the locked ATD test (PR #2399). |
| PR #2413 — `fix/batter-history-doubleheader-20261020` | MLB batter-history identity-gate repair | Part of the batter engine's integrity record cited in the 13 batter drafts. |
| PR #2404 — `docs/capture-spec-confirmation-20261018` | Capture Spec confirmation record | HELD by owner ruling until Thursday's entry capture is committed; Thursday does not wait on it. |

## 8. Freeze protocol (how a draft becomes a test)

Freezing is the owner's act, per family, one family at a time. The
freeze package for a family is: (1) this program's draft doc for the
family, edited only to change its status header and to record the
freeze date and the owner's ruling; (2) its framework config with
`status` flipped and `model_version` re-pinned to the exact engine
build that will price (with the build's commit); (3) the sha256 of
both, recorded in the freeze commit. From that commit forward — and
only from that commit — prospective rows accrue. A frozen test's
terms change only as a new versioned preregistration standing beside
the frozen one, never by editing it. The evaluator stamps the config
status and sha256 into every verdict record, so a readout produced
under a DRAFT config can never present as a frozen verdict.

## 9. Sequencing readout — who can reach a verdict, in what order

1. **Already counting or about to:** Part 2 and anytime-TD open Thu
   Oct 22, 2026 (Part 2B too, if PR #2415 merges in time); LEVEL v2's
   forward leg is already running to Jan 13, 2027; the MLB pitcher
   promotion study executes once after the 2026 World Series.
2. **Nearest draft-to-verdict paths:** the NFL game-market drafts and
   the sibling NBA prop draft — engines wired, captures in spec; each
   needs only its freeze (NFL game markets) or its build's merge +
   freeze (NBA props). The ten NFL prop drafts follow once their
   engine branch merges and the capture subset expands (Section 5);
   TARGETS and the defensive three additionally wait on DraftKings
   listing the markets at all.
3. **CFB:** wiring merge → capture expansion → freeze. Earliest
   realistic verdict is a full season of captured Saturdays away
   (100 graded rows per market at full-board cadence).
4. **MLB drafted families:** freeze-ready now; the binding constraint
   is row throughput under operative-only captures (Section 5) — a
   standing MLB capture job is the single highest-leverage expansion
   in the program, and it is an owner scope decision.
5. **Everything else** waits on its named blocker in Section 4 —
   an eligibility ruling (MLB F5), an input admission (NFL
   derivatives), a data decision (NFL longest plays, first TD),
   a scope ruling (QB interceptions), a build (CBB, MLB greenfield,
   NBA periods/threes), or a market (Section 6). None of those is
   advanced by writing more drafts; each is named so it can be worked
   or ruled on directly.

*Program map prepared Oct 20, 2026 (Rocky). Sources: the NO_ENGINE
inventory (Oct 20, 2026); the frozen Part 2 and Part 2B
preregistrations; Capture Spec V1; the anytime-TD locked test; the
MLB pitcher promotion preregistration; the NFL prop engines build
report (branch `feat/nfl-prop-engines-20261020` @ `8b2775008`); PRs
#2396, #2399, #2403, #2413, #2415, #2416 as state-known records.*
