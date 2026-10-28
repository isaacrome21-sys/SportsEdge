# NHL_ATTEMPT2_V1 — build record (2026-10-28)

**Status: BUILD ONLY — DRAFT, NOT FROZEN. No clock, no screen verdict,
no validation credit, no PLAY.** This package delivers the build work
the merged design (PR #2839, `NHL_SIDES_TOTALS_DESIGN.md`, Blockers)
names as owed before Stage B's window opens Dec 1, 2026: "construction
code + fit are build work owed." The screen adjudication is in
SCREEN_RECORD.md beside this file: NOT_EXECUTABLE, by the design's own
calendar and terms. Stage A (locked home-ice v2 pre-lock, verdict
Nov 30, 2026) is cited there verbatim and is not touched, consumed,
or re-scored by anything here.

## What landed

- `sportsedge/nhl_attempt2.py` — the construction (stdlib only):
  strictly-prior exponentially weighted team xG rates shrunk toward
  league rates; goaltender adjustment (confirmed starter's
  strictly-prior goals-saved-above-xG per game; unconfirmed = weighted
  starter/backup blend, flagged degraded); regulation-first negative
  binomial simulation with the OT/SO layer added once from the
  regulation tie probability; outputs moneyline (incl. OT/SO), puck
  line −1.5/+1.5, totals (final and regulation-only), regulation
  3-way moneyline — all from the one simulation.
- `sportsedge/nhl_attempt2_constants.py` — every constant section-cited
  to the design or the MoneyPuck admission record. Freeze-owed values
  (half-life, both shrinkage weights) are None, and the
  frozen-constants pricing path refuses NHL_ATTEMPT2_NOT_FROZEN while
  they are unpinned — no caller bypass; build-stage pricing takes an
  explicit Params and stamps counted=False / frozen=False /
  validation_credit=False / play_eligible=False.
- `tests/test_nhl_attempt2.py` — 20 tests, all passing (see below).
- `research/nhl_attempt2_build_20261028/fit_constants.py` +
  `fitted_constants.json` — the build-stage dispersion fit.
- `research/nhl_attempt2_build_20261028/landing_check.py` +
  `landing_check_result.json` — end-to-end run on the pinned samples.
- This record + SCREEN_RECORD.md.

## Enforcement, proven

- **Strictly-prior** (admission §2.2): features for date D use only
  rows with gameDate < D. Tests: adding the target game itself and
  later games with extreme xG leaves every rate bit-identical;
  hand-computed weighted-rate known answers. On real data, Anaheim's
  pre-2026-10-20 aggregate from this loader reproduces the admission
  record's own demonstration exactly (8 games, max gameDate 20261019,
  xGF 25.708 / xGA 27.884).
- **xG vintage** (admission §4.1): any fit whose used rows span the
  2025/2026 boundary refuses XG_VINTAGE_POOLING_REFUSED; an undeclared
  treatment name refuses XG_VINTAGE_TREATMENT_UNDECLARED; the one
  declared treatment (SINGLE_VINTAGE_ONLY:rebuilt_2026_27 — the Stage B
  fit sits entirely inside 2026-27) excludes legacy rows and counts
  them. Proven in tests and on real rows in the landing check
  (2,788 legacy rows excluded, 368 rebuilt rows used, at the
  2026-10-26 target date).
- **OT/SO added once** (design §2): unit tests assert the moneyline
  gain over the regulation win probability equals tie mass × share on
  each side, and the expected final total exceeds the expected
  regulation total by exactly tie mass × OT-decision share. (Building
  the totals layer caught a real leak — the folded-tail tie cell at
  the grid's top total initially dropped its OT goal off the end of
  the array; fixed by extending the final-totals grid one goal, and
  the exact-one identities now hold to 1e-9.)

## The fit (design §2: "a dispersion parameter fit on design data")

Declared design set: MoneyPuck all_teams, season 2026 (rebuilt
vintage), situation 'all', playoffGame 0, regular-season window from
2026-10-08, pinned pull verified by hash before reading — 132 games,
528 (mu, g) pairs. Method of moments for Var = phi · mean with each
game's own xG as the mean proxy: raw estimate **0.8208**, below the
Poisson floor; the build constant is **phi = 1.0 (pure Poisson)**.
The raw value and its limitation are recorded in fitted_constants.json:
game-level xG absorbs variation a rate-based mean would leave in the
residuals, so this fit understates dispersion relative to the
construction's actual use. A residuals-around-strictly-prior-rates fit
is the alternative reading — the freeze package adjudicates, and the
freeze fit governs either way.

## Readings taken where the design is silent (freeze package pins each)

1. **Situation basis 'all'** for rate inputs, following the admitted
   collector's strictly-prior aggregate precedent. 'all' includes
   OT-period play; the sim's OUTPUT distributions are regulation
   distributions as designed, and goal conventions stay inside the
   one source (the shootout-deciding goal is not a shot and is absent,
   admission §4.2).
2. **Matchup form** off × def / league, with the league rate the mean
   of the weighted league offensive and defensive rates — the standard
   reading of "offensive/defensive goal rates ... shrunk toward
   league rates."
3. **Half-life in team games**, not days: the design's shrinkage clock
   is "by games played."
4. **Goaltender adjustment** is additive goals-saved-above-xG per game,
   shrunk toward 0 by games played, subtracted from the opposing
   team's mean; the unconfirmed blend pools goalies weighted by games
   played. (Design: "save performance vs shot quality faced,"
   "weighted starter/backup blend.")
5. **No home-ice term.** The attempt-2 draft specifies none — home-ice
   belongs to the separate, locked Stage A home-ice v2 model. The
   landing check's illustrative prices are venue-blind by
   construction, visibly so (all three Oct 26 road teams price
   slightly ahead). This is the freeze package's first adjudication
   item: add a declared home term by amendment, or keep the
   construction venue-blind into Stage B as drafted.
6. **OT/SO parameters are not identifiable from the admitted
   surface** — a one-goal final conflates regulation and OT decisions,
   and the shootout winner is absent from shot-derived goals.
   OT_HOME_WIN_SHARE and OT_DECISION_SHARE ship as neutral 0.5
   placeholders, labeled NOT FITTED in the constants file; the freeze
   package must source them from the NHL API design ground truth the
   design names (design, Inputs — schedule/results ground truth for
   design) or declare constants of its own.
7. **Regular-season window**: fit and landing paths filter to
   gameDate ≥ 20261008 for 2026-27 (the design's Stage A window
   language; admission §4.3 leaves competition windows to the
   consumer). Core rate functions are window-agnostic; the
   collector-parity check deliberately uses unfiltered season rows
   because the admission's demonstration does.

## Freeze-owed (nothing here freezes)

HALF_LIFE_GAMES, SHRINKAGE_PRIOR_GAMES, GOALIE_SHRINKAGE_GAMES;
OT_HOME_WIN_SHARE / OT_DECISION_SHARE fit or declaration; the
dispersion refit on the exact frozen head; the home-ice adjudication
(reading 5); and the preregistration freeze act itself. After a
freeze, the Stage B fit runs on games before Dec 1, 2026 inside the
rebuilt vintage, under the declared treatment already enforced here.

## Verification

- Family tests: **20 passed** (tests/test_nhl_attempt2.py), incl. the
  strictly-prior invariance and known-answer tests, all three vintage
  enforcement tests, goalie known answers, pmf exactness (Poisson) and
  dispersion (negative binomial) checks, the OT/SO exact-once
  identities, and the frozen-path refusal.
- Ruff gate (E9,F821,F822,F823,F811) clean on all new files. No
  dependencies added; manifests untouched.
- Landing check on the pinned samples: pins 6/6 PIN_MATCH; ANA
  strictly-prior parity exact; vintage refusal + declared-treatment
  exclusion on real rows; frozen-path refusal; the full 2026-10-26
  slate (TOR @ CGY, DET @ EDM, LAK @ NYR) priced strictly-prior under
  disclosed illustrative parameters — regulation means 2.85–3.28,
  regulation tie probabilities ≈ 0.16, every output stamped
  counted=False. Full numbers in landing_check_result.json. The slate
  is a machinery proof, NOT a screen and NOT scored against results.
