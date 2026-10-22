"""NBA totals V3: mean of two teams' shrunken historical game-total effects.

Research challenger stacked on V2's real observed_at/identity guards.
No sportsbook input, probabilities, wager eligibility or gate changes.
"""
from __future__ import annotations

from math import isfinite

from .nba_scoring_level_v2 import predict_total as _v2_predict_total


ENGINE = "NBA_TOTALS_PAIR_MEAN_V3_RESEARCH"
PAIR_MEAN_WEIGHT = 0.5


def predict_total(history, *, home, away, as_of):
    """Return the frozen pair-mean challenger on V2's strict PIT cohort.

    The first projection is created by the parent research model, which
    rejects missing independent source refs, fake result availability and
    all future target information. V3 only halves the model's deviations
    from the dynamically measured 2*league baseline.
    """
    parent = _v2_predict_total(history, home=home, away=away, as_of=as_of)
    if parent["status"] != "RESEARCH_PROJECTION":
        return {
            **parent,
            "engine_id": ENGINE,
            "parent_engine": parent["engine_id"],
            "method": "PARENT_V2_REFUSAL_UNCHANGED",
            "research_only": True,
            "play_authority": False,
        }
    league = parent["league_points_per_team"]
    predicted_home = league + PAIR_MEAN_WEIGHT * (parent["predicted_home"] - league)
    predicted_away = league + PAIR_MEAN_WEIGHT * (parent["predicted_away"] - league)
    total = predicted_home + predicted_away
    if not all(isfinite(x) and x > 0 for x in (predicted_home, predicted_away, total)):
        return {
            "engine_id": ENGINE,
            "parent_engine": parent["engine_id"],
            "status": "REFUSED",
            "reason": "NBA_TOTALS_V3_NONPOSITIVE_OR_NONFINITE_PROJECTION",
            "research_only": True,
            "play_authority": False,
        }
    return {
        **parent,
        "engine_id": ENGINE,
        "parent_engine": parent["engine_id"],
        "predicted_home": predicted_home,
        "predicted_away": predicted_away,
        "predicted_total": total,
        "parent_v2_total": parent["predicted_total"],
        "method": "LEAGUE_SCORING_PLUS_MEAN_TWO_SHRUNK_TEAM_TOTAL_EFFECTS",
        "pair_mean_weight": PAIR_MEAN_WEIGHT,
        "historical_screen": "FAILED_2015_2021_DATE_ONLY_SCREEN",
        "market_test": "NOT_ADMITTED_HISTORICAL_REFERENCE",
        "calibration_status": "NOT_VALIDATED",
        "activation_status": "INELIGIBLE_FAILED_EXPLORATORY_SCREEN",
        "research_only": True,
        "play_authority": False,
    }
