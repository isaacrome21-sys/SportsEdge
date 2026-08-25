"""Shared simulation engines."""

from .football import JointScoreSimulator, KeyNumberMarginModel
from .football_path import EngineAPathSimulator, FootballGamePath, ScoringEvent
from .situational import (
    derive_both_teams_to_n,
    derive_largest_lead,
    derive_race_to_n,
    derive_winning_margin_band,
)

__all__ = [
    "JointScoreSimulator",
    "KeyNumberMarginModel",
    "EngineAPathSimulator",
    "FootballGamePath",
    "ScoringEvent",
    "derive_race_to_n",
    "derive_largest_lead",
    "derive_winning_margin_band",
    "derive_both_teams_to_n",
]
