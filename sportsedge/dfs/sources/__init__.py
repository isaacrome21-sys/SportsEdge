"""Live public-source adapters for DraftKings DFS context.

Adapters are intentionally evidence-only: missing public data is UNKNOWN, never an
implicit healthy/active/default state.
"""

from .football_espn import EspnFootballContextClient
from .mlb_statsapi import MLBStatsApiContextClient
from .types import DfsContextEvidence, PlayerAvailability

__all__ = [
    "DfsContextEvidence",
    "PlayerAvailability",
    "EspnFootballContextClient",
    "MLBStatsApiContextClient",
]
