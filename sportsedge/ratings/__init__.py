"""SportsEdge team-rating foundation: explicit opponent-adjusted Elo.

Replaces the opaque ``margin_proxy`` (recent differentials x 0.15, capped)
with a standard per-sport Elo that updates after each game on pre-game
info + opponent quality only. HFA / rest / travel are declared separate
adjustment layers, never buried in the rating or the mean.

Canonical entry point::

    from sportsedge.ratings import get_team_strength, configure

    # once at startup, after loading the verified ratings store:
    configure("NFL", RatingProvider.load("data/ratings/nfl.json"))
    strength = get_team_strength("Kansas City Chiefs", kickoff, "NFL")
    # -> TeamStrength(rating=..., strength_points=..., rated=...)

Public, free data only. Market-blind. Research only. Fail closed.
"""
from __future__ import annotations

from .elo import EloTracker, EloError, expected_score, mov_multiplier
from .history import GameRecord, HistoryError, season_label
from .layers import (
    AdjustmentLayer, DEFAULT_LAYERS, build_means,
    hfa_layer, rest_layer, travel_layer,
)
from .provider import (
    RatingError, RatingProvider, TeamStrength,
    build_provider, clear_configuration, configure, configured,
    get_team_strength,
)
from . import params

__all__ = [
    "AdjustmentLayer", "DEFAULT_LAYERS", "EloError", "EloTracker",
    "GameRecord", "HistoryError", "RatingError", "RatingProvider",
    "TeamStrength", "build_means", "build_provider", "clear_configuration",
    "configure", "configured", "expected_score", "get_team_strength",
    "hfa_layer", "mov_multiplier", "params", "rest_layer", "season_label",
    "travel_layer",
]
