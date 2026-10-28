"""Constants for NHL_ATTEMPT2_V1 (NHL attempt-2 sides / totals).

This is the build-stage form of the constants file the attempt-2
preregistration will pin at its freeze. Every value cites its source:
the merged design draft (research/activation_designs_20261027/
NHL_SIDES_TOTALS_DESIGN.md — "the design") or the merged MoneyPuck
admission record (research/nhl_moneypuck_admission_20261028/
ADMISSION_RECORD.md — "the admission"). STATUS: DRAFT — NOT FROZEN.
No clock runs on these values; the pricing path through the frozen
constants refuses until a freeze pins the freeze-owed values
(NHL_ATTEMPT2_NOT_FROZEN).

Stage A is a different, locked construction (the home-ice v2 pre-lock,
docs/research/nhl_home_ice_v2_prelock.md, locked Sep 29, 2026). Nothing
in this file touches it, cites its terms as this construction's, or
re-opens it.
"""

from __future__ import annotations

CONSTRUCTION_ID = "NHL_ATTEMPT2_V1"
CONSTANTS_ID = "NHL_ATTEMPT2_CONSTANTS_BUILD_20261028"
STATUS = "DRAFT — NOT FROZEN"

# --- Input basis (design section 1; admission sections 2-4) ----------------
# Team rates are built from MoneyPuck game-by-game team rows. The
# admitted collector's strictly-prior aggregate basis is situation
# 'all' (collect_moneypuck.py strictly_prior_team_aggregate default);
# the rates consume that surface. Goal conventions stay inside the one
# source (admission section 4.2): MoneyPuck goals are shot-derived and
# do not count the shootout-deciding goal.
SITUATION_BASIS = "all"

# xG model vintage (admission section 4.1): season >= 2026 carries the
# rebuilt model; seasons <= 2025 are undisclosed legacy. xG must not be
# pooled across that boundary without a declared cross-vintage
# treatment in the consuming preregistration.
VINTAGE_REBUILT_2026_27 = "rebuilt_2026_27"
VINTAGE_UNDISCLOSED_LEGACY = "undisclosed_legacy"
VINTAGE_BOUNDARY_SEASON = 2026

# The one treatment the design + admission declare for attempt 2:
# admission section 4.1 — "The attempt-2 Stage B fit (games before
# Dec 1, 2026) sits entirely inside the 2026-27 season and therefore
# inside one disclosed vintage." Restriction to the single rebuilt
# vintage; legacy rows are excluded and counted, never pooled.
DECLARED_CROSS_VINTAGE_TREATMENT = "SINGLE_VINTAGE_ONLY:rebuilt_2026_27"

# Competition window (design, Stage A citation: "2026-27 regular-season
# games Oct 8 - Nov 30, 2026"; admission section 4.3: season files
# include late-September preseason dates and "consumers apply their own
# competition windows"). Fit/pricing feature paths filter to
# regular-season rows on or after this date for the 2026-27 season.
REGULAR_SEASON_START = {2026: 20261008}

# --- Rate form (design section 1) -------------------------------------------
# "Team offensive/defensive goal rates built from MoneyPuck shot-level
# expected goals ..., strictly prior games only, exponentially weighted
# with a half-life fixed at freeze, shrunk toward league rates by games
# played."
# FORM pinned by this build (readings recorded in BUILD_RECORD.md):
# exponential weights over team games (the design's clock is games:
# shrinkage is "by games played"), w = 0.5 ** (games_ago / half_life);
# shrinkage rate = (sum w*x + K * league_rate) / (sum w + K);
# matchup mean = off_rate(team) * def_rate(opponent) / league_rate.
# VALUES: the design fixes the half-life AT FREEZE and names no
# shrinkage weight, so both are freeze-owed here (None). The frozen
# pricing path refuses while they are None.
HALF_LIFE_GAMES = None         # FREEZE-OWED (design section 1)
SHRINKAGE_PRIOR_GAMES = None   # FREEZE-OWED (design section 1)
GOALIE_SHRINKAGE_GAMES = None  # FREEZE-OWED (design section 1 family)

# --- Goaltender adjustment form (design section 1) --------------------------
# "Goaltender adjustment from the confirmed starter's strictly-prior
# save performance vs shot quality faced; unconfirmed starter = the
# team's weighted starter/backup blend, and the row is flagged
# degraded." Build form (reading recorded in BUILD_RECORD.md): a
# goalie's goals-saved-above-xG per game, (xGoals faced - goals
# allowed) / games over strictly-prior rows, shrunk toward 0 by games
# played, subtracted from the opposing team's matchup mean. The blend
# weights goalies by strictly-prior games played.

# --- Regulation-first simulation (design section 2) -------------------------
# "Regulation goal distributions per team (Poisson with a dispersion
# parameter fit on design data), then OT/SO resolution layered on the
# regulation result — OT/SO probability mass is added once, from the
# regulation tie probability."
# Build form: negative binomial with Var = DISPERSION_PHI * mean
# (phi = 1.0 is exact Poisson). DISPERSION_PHI is the build-stage fit
# (research/nhl_attempt2_build_20261028/fit_constants.py; provenance in
# fitted_constants.json beside it: declared design set of 132
# regular-season 2026-27 games through the pinned Oct 28 pull, 528
# (mu, g) pairs, raw method-of-moments estimate 0.8208 floored to the
# Poisson value 1.0). The freeze fit governs.
DISPERSION_PHI = 1.0

# OT/SO layer parameters. The design fixes the STRUCTURE (mass added
# once, from the regulation tie probability) but no values, and the
# admitted MoneyPuck team surface cannot identify them: a one-goal
# final conflates regulation and OT decisions, and the shootout winner
# is absent from shot-derived goals (see fitted_constants.json,
# observables_for_the_record). Build-stage NEUTRAL placeholders, NOT
# FITTED — the freeze package must source these from the NHL API
# design ground truth the design names (design, Inputs) or declare
# constants of its own.
OT_HOME_WIN_SHARE = 0.5        # BUILD_STAGE_NEUTRAL — NOT FITTED
OT_DECISION_SHARE = 0.5        # BUILD_STAGE_NEUTRAL — NOT FITTED
                               # (share of regulation ties decided in
                               # OT rather than the shootout; drives the
                               # single added goal in the totals layer)

# Computational bounds (build choices, not design terms): goal grid
# 0..MAX_GOALS per team with the tail folded into the last cell (mass
# is preserved exactly; the folded tail at NHL means is < 1e-6), and a
# floor for goalie-adjusted means so a distribution always exists.
MAX_GOALS = 12
MIN_MEAN = 0.05
