"""Market-blind NFL return-touchdown hazard used by the shared game path.

This is a structural event generator, not a prop model. Return-touchdown events
must be attached to a concrete turnover/kick/punt event before any market readout
may consume them. Candidate rates remain promotion blockers until fitted from
point-in-time return data.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class NFLReturnScoringProfile:
    team: str
    kickoff_return_td_rate: float = 0.006
    punt_return_td_rate: float = 0.008
    turnover_return_td_rate: float = 0.025

    def __post_init__(self) -> None:
        if not str(self.team).strip():
            raise ValueError("RETURN_SCORING_TEAM_REQUIRED")
        for name in (
            "kickoff_return_td_rate",
            "punt_return_td_rate",
            "turnover_return_td_rate",
        ):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"RETURN_SCORING_RATE_OUT_OF_RANGE:{name}")


class NFLReturnScoringResolver:
    """Seeded return-TD resolver over concrete return opportunities."""

    def __init__(
        self,
        home_profile: NFLReturnScoringProfile,
        away_profile: NFLReturnScoringProfile,
        *,
        seed: int | None = None,
    ) -> None:
        if seed is None:
            raise ValueError("EXPLICIT_SEED_REQUIRED")
        if isinstance(seed, bool) or not isinstance(seed, (int, np.integer)):
            raise ValueError("seed must be an integer")
        if not isinstance(home_profile, NFLReturnScoringProfile) or not isinstance(away_profile, NFLReturnScoringProfile):
            raise TypeError("NFL_RETURN_SCORING_PROFILE_REQUIRED")
        if home_profile.team == away_profile.team:
            raise ValueError("RETURN_SCORING_HOME_AWAY_COLLISION")
        self.home_profile = home_profile
        self.away_profile = away_profile
        self.seed = int(seed)
        self.rng = np.random.default_rng(self.seed)

    def _profile(self, team: str) -> NFLReturnScoringProfile:
        if team == self.home_profile.team:
            return self.home_profile
        if team == self.away_profile.team:
            return self.away_profile
        raise ValueError(f"RETURN_SCORING_TEAM_NOT_FOUND:{team}")

    def is_touchdown(self, team: str, return_type: str) -> bool:
        profile = self._profile(team)
        normalized = str(return_type).strip().upper()
        if normalized == "KICKOFF":
            rate = profile.kickoff_return_td_rate
        elif normalized == "PUNT":
            rate = profile.punt_return_td_rate
        elif normalized == "TURNOVER":
            rate = profile.turnover_return_td_rate
        else:
            raise ValueError(f"UNSUPPORTED_RETURN_TYPE:{return_type}")
        return bool(self.rng.random() < float(rate))
