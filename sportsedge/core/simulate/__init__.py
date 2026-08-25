"""Shared simulation engines."""

from .drive_play import EngineADrivePlaySimulator, FootballPlayPath, PlayEvent, TeamDriveProfile
from .football import JointScoreSimulator, KeyNumberMarginModel
from .football_path import EngineAPathSimulator, FootballGamePath, ScoringEvent
from .player_markets import derive_player_stat_market
from .situational import (
    derive_both_teams_to_n,
    derive_largest_lead,
    derive_race_to_n,
    derive_winning_margin_band,
)
from .special_teams import (
    EngineCSpecialTeamsResolver,
    ResolvedFootballPath,
    SpecialTeamsEvent,
    SpecialTeamsProfile,
)
from .usage import (
    AttributedFootballPath,
    AttributedPlay,
    EngineBUsageAllocator,
    PlayerUsageProfile,
    TeamUsageProfile,
)

__all__ = [
    "JointScoreSimulator",
    "KeyNumberMarginModel",
    "EngineAPathSimulator",
    "FootballGamePath",
    "ScoringEvent",
    "EngineADrivePlaySimulator",
    "FootballPlayPath",
    "PlayEvent",
    "TeamDriveProfile",
    "SpecialTeamsProfile",
    "SpecialTeamsEvent",
    "ResolvedFootballPath",
    "EngineCSpecialTeamsResolver",
    "PlayerUsageProfile",
    "TeamUsageProfile",
    "AttributedPlay",
    "AttributedFootballPath",
    "EngineBUsageAllocator",
    "derive_player_stat_market",
    "derive_race_to_n",
    "derive_largest_lead",
    "derive_winning_margin_band",
    "derive_both_teams_to_n",
]
