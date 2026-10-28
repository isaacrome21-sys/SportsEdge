# DESIGN + PREREGISTRATION DRAFT — CFB Game Props V1 (`CFB_GAME_PROPS_DERIVED_V1`)

# DRAFT — NOT FROZEN. NO CLOCK RUNS UNDER THIS DOCUMENT.

- Status: `DESIGN_ONLY` — derived-probability construction specified;
  pilot phase is **shadow-pricing only** (model prices logged against
  captured DK offers; no picks, no card rows, no clock).
- Date drafted: 2026-10-27
- Family in scope: CFB **game props** — game-level propositions that
  are neither sides/totals/team totals nor player stats. Design scope
  (each category is admitted to this family's registry only when a
  captured DK offer for it exists — see §3):
  first team to score; first scoring play type (TD / FG / safety);
  first team to score a TD; both teams to score (yes/no); total
  touchdowns O/U; total field goals O/U; overtime yes/no; defensive
  or special-teams touchdown yes/no; race to 10 / 20 points; winning
  margin bands.
- Engine under test: `CFB_GAME_PROPS_DERIVED_V1` (§2).

## 0. Up-front honesty

Game props have the same historical void as player props (Gap G1):
no historical CFB prop lines exist in any admitted source, so **no
historical market screen is possible** and none is pretended here.
What history *can* test is calibration: whether the construction's
event probabilities match realized event frequencies on past games
better than base rates do. Market validation is forward-only, against
captured DK offers, and — because DK's CFB prop board is thinner and
more selective than its NFL board — volume gates below are sized to
that reality rather than copied from another family.

## 1. Question

Can a drive-level scoring-path model produce **calibrated** joint
event probabilities for game props (who scores first, how the scoring
is composed, whether the game reaches overtime) that beat the
no-vig probabilities in DraftKings' captured prop offers on forward
slates, in the categories DK actually posts for CFB?

## 2. Construction

A Monte Carlo **drive-path simulation** per game:

- Each team's drive outcomes (TD / FG / punt / turnover / safety /
  end-of-half) are drawn from walk-forward, opponent-adjusted drive
  outcome rates built from cfbfastR play-by-play (the possession
  layer shared as *inputs discipline* with the team-totals design —
  rates computed from raw PBP under the same PIT rules — but this is
  a separate construction with its own fitted objects and its own
  verdict; it neither inherits nor confers any team-totals result).
- Possession order, kickoff/receive tendencies, and late-game state
  (score differential by quarter) drive the path; the simulation
  emits the joint distribution over the §-header events directly
  (first-score identity and type fall out of the first scoring drive;
  OT from tied regulation paths under NCAA OT rules as a probability
  adjustment, labeled as modeled, not simulated possession-by-
  possession).
- Simulation count per game fixed at build time and recorded (seed
  discipline as in the program's other Monte Carlo work); the same
  seed policy binds every shadow and (future) counted run.
- **No market input** to any probability. **No QB-identity input**
  (G3). Illinois exclusion identical to the rest of this pack
  (`ILLINOIS_COLLEGE_EXCLUDED`, first, both teams).

**Declared dependency (not hidden):** if the team-totals screen
fails *and* its post-mortem attributes the failure to the PBP
possession inputs themselves (rather than to the team-total claim),
this construction's fitted objects must be re-derived under a new
version before any freeze request. A team-totals SCREEN_FAIL does not
automatically kill this family, and a SCREEN_PASS does not advance
it. Each stands on its own test.

## 3. Category admission rule

DK's CFB game-prop board varies by game and week. A category enters
the family's active registry only when the capture program holds a
real captured DK offer for it (event page, verbatim, with prices and
capture timestamp, under the lane's comment-material discipline).
Categories never captured are never priced, never counted, and are
listed as `NOT_POSTED_BY_BOOK` in pilot reports — the family does not
invent a board DK didn't post.

## 4. Historical calibration diagnostic (cannot validate the family)

On 2023–2025 design seasons (Week 5+, FBS vs FBS, walk-forward):
per-category Brier score and log loss of the construction's event
probabilities vs (a) realized-frequency base rates (walk-forward),
(b) a market-free straw model (league drive rates, no team traits).
**Kill rule (fixed here):** if the construction does not beat (a) on
Brier score for at least two-thirds of the categories it prices, it
is recorded FAILED_DIAGNOSTIC and retired before any freeze request.
Passing earns the pilot (§5) and, after it, the right to request a
freeze.

## 5. Pilot (shadow-pricing) — the only phase this draft authorizes

- For every captured DK game-prop offer on a CFB slate, log the
  construction's probability, the DK price, and the no-vig implied
  probability, with full capture provenance (the #2792 receipts
  discipline). No picks are published; no rows reach a card; the log
  is the deliverable.
- Pilot exit report (after ≥4 slates with captured offers): category
  volume (offers per category per slate — the honest measure of
  whether this family can ever support a forward test), calibration
  on settled shadow rows (Brier vs the DK no-vig probabilities,
  labeled SHADOW — not CLV, not a verdict), and a go/no-go
  recommendation for a freeze request.
- If captured volume is structurally tiny (e.g. DK posts CFB game
  props only on a handful of marquee games), the report says so and
  the family rests at PILOT rather than manufacturing a test the
  board cannot feed.

## 6. Forward test (proposed terms; bind only on a future owner freeze)

- Only categories in the active registry (§3) and only rows with a
  real captured entry/close pair (validity windows inherited from
  the team-totals draft in this pack).
- Primary test per category, then pooled: mean (model − no-vig close)
  probability calibration **and** picked-row CLV, where a row is
  PICKED when the model's probability exceeds the entry no-vig
  probability by ≥ 5 percentage points (stated here, before data).
  Legs mirror the team-totals 7a–7d pattern adapted to probability
  outcomes (Brier-difference CI instead of ΔMAE), game-cluster
  bootstrap 10,000 at 1 − α/k, α = 0.05, k recorded at freeze/review.
- Gates (minimums, per the pilot's volume evidence — to be fixed in
  the frozen revision from pilot data, not invented here): full
  slates, distinct games, priced rows, and picked rows, with a
  per-category minimum so the verdict cannot ride on one category.
- Verdicts and effect language as in the team-totals draft.

## 7. What this design does not do

No freeze, no clock, no picks, no registration change, no historical
market claim. Shadow numbers are labeled SHADOW everywhere they
appear and are never CLV and never a verdict.
