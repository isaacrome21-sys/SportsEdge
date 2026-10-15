"""Named truthful blockers for the MLB game exotics (matrix M50).

DraftKings offers a game-props slate beyond the core families
(enumerated on the Oct 13 2026 board, CATALOG_MLB.md GAME PROPS /
1ST OF GAME tabs; five of the names are census keys in
config/dk_inspected_menu_census_v1.json, group "exotic"): Race to
3/4/5/6/7 Runs (3-way with Neither), Both Teams to Score X+ Runs
ladder (1+..9+), Grand Slam Yes/No, Extra Innings Yes/No, Winning
Margin, Correct Score, a team to bat in the bottom of the 9th
Yes/No, Inning of First/Last Run, Team with Highest Scoring
Inning, Team to Win Most Innings, Team Total Runs Odd/Even, and
First Scoring Play -- Number of Runs. None of these names is among
the 89 matrix markets in sportsedge.canonical_coverage (that table
is the matrix contract, exact by test). Intake rows for them used
to die at the generic NO_VERIFIED_MODEL_FOR_THIS_MARKET fallback.
This module gives the names first-class form on the canonical card
with the truthful blockers (the mlb_total_hits pattern); the
matrix's stated correct end state for this set is a named blocker
per family unless prioritized. The blockers differ because the
missing constructions differ:

* SCORE_PATH_UNBUILT -- the race, first/last-run-inning, highest-
  scoring-inning, most-innings-won, bottom-of-9th and first-
  scoring-play forms settle on the ORDER and TIMING of scoring.
  The canonical constructions produce final-score (or cumulative-
  period) distributions only; no inning-by-inning score path --
  and, for the first scoring play, no play-level path -- exists on
  this path, and a final-score joint carries no path information.
* PLAY_EVENT_POOL_UNBUILT -- a grand slam is a bases-loaded home
  run: a play event with bases state. No verified strictly-prior
  play-event pool with bases state exists on the canonical path
  (the same structural gap the M49 first-plate-appearance gate
  names for PA outcomes).
* FULL_GAME_DERIVED_READOUT_UNBUILT -- the BTTS ladder, correct
  score, extra innings and team-total odd/even forms are derivable
  in principle from a full-game (away, home) score joint, and
  their F5 analogues exist as deployment-gated derived readouts;
  but no full-game readout or quote binding exists for any of
  them, and the one full-game joint on the canonical path (the
  M7 totals construction) exposes only the Over / Exactly / Under
  total readout and is itself deployment-gated.

WINNING_MARGIN remains owned by the Phase-7 coverage dispatch:
sportsedge.market_coverage normalizes it to MARGIN_BAND, a football
construction, but the inspected MLB menu marks Winning Margin offered.
The coverage layer therefore terminates MLB rows at the truthful
NO_ENGINE: FULL_GAME_DERIVED_READOUT_UNBUILT gate, with no pricing.
This module does not re-own or duplicate the alias.

Nothing here prices: every row terminates BLOCKED with the gate
named. No registry/deployment/validation state is touched.
"""
from __future__ import annotations

from typing import Any, Mapping

_SCORE_PATH_GATE = "SCORE_PATH_UNBUILT"
_SCORE_PATH_DETAIL = (
    "this market settles on the order and timing of scoring "
    "(which team reaches a run mark first, the inning of the "
    "first/last run, per-inning winners, the bottom-of-9th game "
    "state, or the first scoring play); the canonical "
    "constructions produce final-score (or cumulative-period) "
    "distributions only -- no inning-by-inning score path, and no "
    "play-level path, exists on this path, and a final-score "
    "joint carries no path information. Pricing stays refused "
    "until a verified score-path construction exists.")
_PLAY_EVENT_GATE = "PLAY_EVENT_POOL_UNBUILT"
_PLAY_EVENT_DETAIL = (
    "a grand slam is a bases-loaded home run -- a play event "
    "with bases state; no verified strictly-prior play-event "
    "pool carrying bases state exists on the canonical path "
    "(StatsAPI play-by-play carries the events, but no "
    "construction consumes them into a PIT event pool). Pricing "
    "stays refused until one exists.")
_READOUT_GATE = "FULL_GAME_DERIVED_READOUT_UNBUILT"
_READOUT_DETAIL = (
    "this form is derivable in principle from a full-game "
    "(away, home) score joint, and its F5 analogue exists as a "
    "deployment-gated derived readout; but no full-game readout "
    "or quote binding exists for it -- the one full-game joint "
    "on the canonical path (the M7 totals construction) exposes "
    "only the Over / Exactly / Under total readout and is itself "
    "deployment-gated. Pricing stays refused until a full-game "
    "readout and binding exist.")

# canonical market -> (gate code, detail)
EXOTIC_GATES: dict[str, tuple[str, str]] = {
    "RACE_TO_RUNS": (_SCORE_PATH_GATE, _SCORE_PATH_DETAIL),
    "INNING_OF_FIRST_RUN": (_SCORE_PATH_GATE, _SCORE_PATH_DETAIL),
    "INNING_OF_LAST_RUN": (_SCORE_PATH_GATE, _SCORE_PATH_DETAIL),
    "TEAM_WITH_HIGHEST_SCORING_INNING": (
        _SCORE_PATH_GATE, _SCORE_PATH_DETAIL),
    "TEAM_TO_WIN_MOST_INNINGS": (_SCORE_PATH_GATE, _SCORE_PATH_DETAIL),
    "BAT_IN_BOTTOM_9TH": (_SCORE_PATH_GATE, _SCORE_PATH_DETAIL),
    "FIRST_SCORING_PLAY_RUNS": (_SCORE_PATH_GATE, _SCORE_PATH_DETAIL),
    "GRAND_SLAM": (_PLAY_EVENT_GATE, _PLAY_EVENT_DETAIL),
    "BOTH_TEAMS_TO_SCORE_RUNS": (_READOUT_GATE, _READOUT_DETAIL),
    "CORRECT_SCORE": (_READOUT_GATE, _READOUT_DETAIL),
    "EXTRA_INNINGS": (_READOUT_GATE, _READOUT_DETAIL),
    "TEAM_TOTAL_ODD_EVEN": (_READOUT_GATE, _READOUT_DETAIL),
}

EXOTIC_ALIASES: dict[str, str] = {
    # Catalog rungs: Race to 3/4/5/6/7 Runs (3-way with Neither).
    "RACE_TO_3_RUNS": "RACE_TO_RUNS",
    "RACE_TO_4_RUNS": "RACE_TO_RUNS",
    "RACE_TO_5_RUNS": "RACE_TO_RUNS",
    "RACE_TO_6_RUNS": "RACE_TO_RUNS",
    "RACE_TO_7_RUNS": "RACE_TO_RUNS",
    "RACE_TO_X_RUNS": "RACE_TO_RUNS",
    "FIRST_RUN_INNING": "INNING_OF_FIRST_RUN",
    "LAST_RUN_INNING": "INNING_OF_LAST_RUN",
    "TEAM_HIGHEST_SCORING_INNING": "TEAM_WITH_HIGHEST_SCORING_INNING",
    "HIGHEST_SCORING_INNING_TEAM": "TEAM_WITH_HIGHEST_SCORING_INNING",
    "TEAM_MOST_INNINGS_WON": "TEAM_TO_WIN_MOST_INNINGS",
    "MOST_INNINGS_WON": "TEAM_TO_WIN_MOST_INNINGS",
    "TEAM_TO_BAT_IN_BOTTOM_9TH": "BAT_IN_BOTTOM_9TH",
    "HOME_TEAM_TO_BAT_IN_BOTTOM_9TH": "BAT_IN_BOTTOM_9TH",
    "BOTTOM_OF_9TH_BAT": "BAT_IN_BOTTOM_9TH",
    "FIRST_SCORING_PLAY": "FIRST_SCORING_PLAY_RUNS",
    "FIRST_SCORING_PLAY_NUMBER_OF_RUNS": "FIRST_SCORING_PLAY_RUNS",
    "GRAND_SLAM_YES_NO": "GRAND_SLAM",
    "BTTS": "BOTH_TEAMS_TO_SCORE_RUNS",
    "BOTH_TEAMS_TO_SCORE": "BOTH_TEAMS_TO_SCORE_RUNS",
    "GAME_CORRECT_SCORE": "CORRECT_SCORE",
    "FULL_GAME_CORRECT_SCORE": "CORRECT_SCORE",
    "EXTRA_INNINGS_YES_NO": "EXTRA_INNINGS",
    "GOES_TO_EXTRA_INNINGS": "EXTRA_INNINGS",
    "TEAM_TOTAL_RUNS_ODD_EVEN": "TEAM_TOTAL_ODD_EVEN",
    "TEAM_TOTAL_ODD_OR_EVEN": "TEAM_TOTAL_ODD_EVEN",
}

EXOTIC_MARKETS = frozenset(EXOTIC_GATES) | frozenset(EXOTIC_ALIASES)


def canonical_exotic_market(market: Any) -> str | None:
    """Canonical exotic market for an intake spelling, else None."""
    name = str(market or "").strip().upper()
    if name in EXOTIC_GATES:
        return name
    return EXOTIC_ALIASES.get(name)


def exotic_blocked_row(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """Fail-closed card row naming the exotic gate.

    Returns None when the row's market is not an M50 exotic market.
    Row shape mirrors canonical_coverage.blocked_row_for.
    """
    canonical = canonical_exotic_market(row.get("market"))
    if canonical is None:
        return None
    gate, detail = EXOTIC_GATES[canonical]
    return {
        "status": "NO_MODEL_OR_MARKET",
        "reason": ("NO_ENGINE: " + gate + " — " + detail)[:400],
        "blocker": "NO_ENGINE",
        "blocker_detail": detail,
        "coverage_market": canonical,
        "exotic_gate": gate,
        "sport": "MLB",
        "market": row.get("market"),
        "selection": row.get("side") or row.get("selection"),
        "player_name": row.get("player_name") or row.get("label"),
        "research_only": True, "official_authority": False,
        "model_p_authority": False, "staking_authority": False,
    }
