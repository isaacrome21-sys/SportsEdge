"""Engine C field-position transitions for the 2026 NFL rule set.

This layer does not simulate a game or price a market. It resolves possession
transitions that Engine A cannot determine by itself: ordinary kickoffs,
declared onside kicks, punts, missed field goals and turnovers. The returned
next-yardline is always expressed from the *next offense's* perspective as
``yardline_100`` (distance to the opponent goal line).

All rates and yardage distributions here are transparent structural candidates
until fitted from point-in-time historical special-teams data.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class NFLFieldPositionProfile:
    team: str
    deep_touchback_rate: float = 0.45
    landing_touchback_rate: float = 0.05
    kickoff_return_yards_mean: float = 25.0
    kickoff_return_yards_sd: float = 8.0
    punt_net_yards_mean: float = 41.0
    punt_net_yards_sd: float = 8.0
    onside_attempt_rate_when_trailing: float = 0.0
    onside_recovery_rate: float = 0.12
    onside_kicking_recovery_yardline_100: int = 55
    onside_receiving_recovery_yardline_100: int = 45

    def __post_init__(self) -> None:
        if not str(self.team).strip():
            raise ValueError("FIELD_POSITION_TEAM_REQUIRED")
        for name in (
            "deep_touchback_rate",
            "landing_touchback_rate",
            "onside_attempt_rate_when_trailing",
            "onside_recovery_rate",
        ):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"FIELD_POSITION_RATE_OUT_OF_RANGE:{name}")
        if self.deep_touchback_rate + self.landing_touchback_rate > 1.0:
            raise ValueError("KICKOFF_TOUCHBACK_RATE_SUM_INVALID")
        for name in (
            "kickoff_return_yards_mean",
            "kickoff_return_yards_sd",
            "punt_net_yards_mean",
            "punt_net_yards_sd",
        ):
            value = float(getattr(self, name))
            if value < 0:
                raise ValueError(f"FIELD_POSITION_VALUE_NEGATIVE:{name}")
        for name in (
            "onside_kicking_recovery_yardline_100",
            "onside_receiving_recovery_yardline_100",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 99:
                raise ValueError(f"FIELD_POSITION_YARDLINE_INVALID:{name}")


@dataclass(frozen=True)
class NFLPossessionTransition:
    transition_index: int
    transition_type: str
    source_play_id: int | None
    next_drive_id: int
    period: int
    clock_seconds_remaining: int
    from_team: str
    nominal_receiving_team: str
    next_possession_team: str
    next_yardline_100: int
    return_yards: int | None = None
    net_kick_yards: int | None = None
    kicking_team_was_trailing: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.transition_index, bool) or not isinstance(self.transition_index, int) or self.transition_index <= 0:
            raise ValueError("FIELD_POSITION_TRANSITION_INDEX_INVALID")
        if self.source_play_id is not None and (
            isinstance(self.source_play_id, bool)
            or not isinstance(self.source_play_id, int)
            or self.source_play_id <= 0
        ):
            raise ValueError("FIELD_POSITION_SOURCE_PLAY_ID_INVALID")
        if isinstance(self.next_drive_id, bool) or not isinstance(self.next_drive_id, int) or self.next_drive_id <= 0:
            raise ValueError("FIELD_POSITION_NEXT_DRIVE_ID_INVALID")
        if self.period not in (1, 2, 3, 4):
            raise ValueError("FIELD_POSITION_PERIOD_INVALID")
        if not 0 <= self.clock_seconds_remaining <= 900:
            raise ValueError("FIELD_POSITION_CLOCK_INVALID")
        if not str(self.transition_type).strip():
            raise ValueError("FIELD_POSITION_TRANSITION_TYPE_REQUIRED")
        for team in (self.from_team, self.nominal_receiving_team, self.next_possession_team):
            if not str(team).strip():
                raise ValueError("FIELD_POSITION_TRANSITION_TEAM_REQUIRED")
        if isinstance(self.next_yardline_100, bool) or not isinstance(self.next_yardline_100, int) or not 1 <= self.next_yardline_100 <= 99:
            raise ValueError("FIELD_POSITION_NEXT_YARDLINE_INVALID")
        if self.return_yards is not None and self.return_yards < 0:
            raise ValueError("FIELD_POSITION_RETURN_YARDS_INVALID")
        if self.net_kick_yards is not None and self.net_kick_yards < 0:
            raise ValueError("FIELD_POSITION_NET_KICK_YARDS_INVALID")
        if not isinstance(self.kicking_team_was_trailing, bool):
            raise ValueError("FIELD_POSITION_TRAILING_FLAG_INVALID")
        if "ONSIDE" in self.transition_type and not self.kicking_team_was_trailing:
            raise ValueError("ONSIDE_REQUIRES_TRAILING_KICKING_TEAM")


class NFLFieldPositionResolver:
    """Seeded, market-blind Engine C possession transition resolver."""

    def __init__(
        self,
        home_profile: NFLFieldPositionProfile,
        away_profile: NFLFieldPositionProfile,
        *,
        seed: int | None = None,
    ) -> None:
        if seed is None:
            raise ValueError("EXPLICIT_SEED_REQUIRED")
        if isinstance(seed, bool) or not isinstance(seed, (int, np.integer)):
            raise ValueError("seed must be an integer")
        if not isinstance(home_profile, NFLFieldPositionProfile) or not isinstance(away_profile, NFLFieldPositionProfile):
            raise TypeError("NFL_FIELD_POSITION_PROFILE_REQUIRED")
        if home_profile.team == away_profile.team:
            raise ValueError("FIELD_POSITION_HOME_AWAY_COLLISION")
        self.home_profile = home_profile
        self.away_profile = away_profile
        self.seed = int(seed)
        self.rng = np.random.default_rng(self.seed)

    def _profile(self, team: str) -> NFLFieldPositionProfile:
        if team == self.home_profile.team:
            return self.home_profile
        if team == self.away_profile.team:
            return self.away_profile
        raise ValueError(f"FIELD_POSITION_TEAM_NOT_FOUND:{team}")

    @staticmethod
    def _period_clock(period: int, clock_seconds_remaining: int) -> tuple[int, int]:
        if period not in (1, 2, 3, 4):
            raise ValueError("FIELD_POSITION_PERIOD_INVALID")
        if not 0 <= clock_seconds_remaining <= 900:
            raise ValueError("FIELD_POSITION_CLOCK_INVALID")
        return period, clock_seconds_remaining

    def kickoff(
        self,
        *,
        transition_index: int,
        source_play_id: int | None,
        next_drive_id: int,
        kicking_team: str,
        receiving_team: str,
        period: int,
        clock_seconds_remaining: int,
        kicking_team_trailing: bool,
        label: str = "KICKOFF",
        allow_onside: bool = True,
    ) -> NFLPossessionTransition:
        self._period_clock(period, clock_seconds_remaining)
        if kicking_team == receiving_team:
            raise ValueError("KICKOFF_TEAM_COLLISION")
        kicking = self._profile(kicking_team)
        receiving = self._profile(receiving_team)
        trailing = bool(kicking_team_trailing)

        if (
            allow_onside
            and trailing
            and self.rng.random() < kicking.onside_attempt_rate_when_trailing
        ):
            kicking_recovers = bool(self.rng.random() < kicking.onside_recovery_rate)
            return NFLPossessionTransition(
                transition_index=transition_index,
                transition_type=(
                    "ONSIDE_RECOVERED_KICKING"
                    if kicking_recovers
                    else "ONSIDE_RECOVERED_RECEIVING"
                ),
                source_play_id=source_play_id,
                next_drive_id=next_drive_id,
                period=period,
                clock_seconds_remaining=clock_seconds_remaining,
                from_team=kicking_team,
                nominal_receiving_team=receiving_team,
                next_possession_team=kicking_team if kicking_recovers else receiving_team,
                next_yardline_100=(
                    kicking.onside_kicking_recovery_yardline_100
                    if kicking_recovers
                    else kicking.onside_receiving_recovery_yardline_100
                ),
                kicking_team_was_trailing=True,
            )

        draw = self.rng.random()
        if draw < kicking.deep_touchback_rate:
            transition_type = f"{label}_TOUCHBACK_35"
            yardline = 65
            return_yards = None
        elif draw < kicking.deep_touchback_rate + kicking.landing_touchback_rate:
            transition_type = f"{label}_TOUCHBACK_20"
            yardline = 80
            return_yards = None
        else:
            yards = int(round(self.rng.normal(
                receiving.kickoff_return_yards_mean,
                receiving.kickoff_return_yards_sd,
            )))
            yards = max(1, min(50, yards))
            transition_type = f"{label}_RETURN"
            yardline = max(50, min(99, 100 - yards))
            return_yards = yards

        return NFLPossessionTransition(
            transition_index=transition_index,
            transition_type=transition_type,
            source_play_id=source_play_id,
            next_drive_id=next_drive_id,
            period=period,
            clock_seconds_remaining=clock_seconds_remaining,
            from_team=kicking_team,
            nominal_receiving_team=receiving_team,
            next_possession_team=receiving_team,
            next_yardline_100=yardline,
            return_yards=return_yards,
            kicking_team_was_trailing=trailing,
        )

    def punt(
        self,
        *,
        transition_index: int,
        source_play_id: int,
        next_drive_id: int,
        punting_team: str,
        receiving_team: str,
        period: int,
        clock_seconds_remaining: int,
        kicking_yardline_100: int,
    ) -> NFLPossessionTransition:
        self._period_clock(period, clock_seconds_remaining)
        if not 1 <= int(kicking_yardline_100) <= 99:
            raise ValueError("PUNT_YARDLINE_INVALID")
        profile = self._profile(punting_team)
        net = int(round(self.rng.normal(profile.punt_net_yards_mean, profile.punt_net_yards_sd)))
        net = max(0, min(80, net))
        remaining_to_goal = int(kicking_yardline_100) - net
        if remaining_to_goal <= 0:
            transition_type = "PUNT_TOUCHBACK_20"
            next_yardline = 80
        else:
            transition_type = "PUNT_RETURN"
            next_yardline = max(1, min(99, 100 - remaining_to_goal))
        return NFLPossessionTransition(
            transition_index=transition_index,
            transition_type=transition_type,
            source_play_id=source_play_id,
            next_drive_id=next_drive_id,
            period=period,
            clock_seconds_remaining=clock_seconds_remaining,
            from_team=punting_team,
            nominal_receiving_team=receiving_team,
            next_possession_team=receiving_team,
            next_yardline_100=next_yardline,
            net_kick_yards=net,
        )

    def missed_field_goal(
        self,
        *,
        transition_index: int,
        source_play_id: int,
        next_drive_id: int,
        kicking_team: str,
        receiving_team: str,
        period: int,
        clock_seconds_remaining: int,
        line_of_scrimmage_yardline_100: int,
    ) -> NFLPossessionTransition:
        self._period_clock(period, clock_seconds_remaining)
        los = int(line_of_scrimmage_yardline_100)
        if not 1 <= los <= 99:
            raise ValueError("MISSED_FIELD_GOAL_YARDLINE_INVALID")
        kick_spot_distance_to_receiving_goal = los + 7
        next_yardline = (
            80
            if kick_spot_distance_to_receiving_goal <= 20
            else 100 - kick_spot_distance_to_receiving_goal
        )
        next_yardline = max(1, min(99, int(next_yardline)))
        return NFLPossessionTransition(
            transition_index=transition_index,
            transition_type="MISSED_FIELD_GOAL",
            source_play_id=source_play_id,
            next_drive_id=next_drive_id,
            period=period,
            clock_seconds_remaining=clock_seconds_remaining,
            from_team=kicking_team,
            nominal_receiving_team=receiving_team,
            next_possession_team=receiving_team,
            next_yardline_100=next_yardline,
        )

    def turnover(
        self,
        *,
        transition_index: int,
        source_play_id: int,
        next_drive_id: int,
        offense_team: str,
        defense_team: str,
        period: int,
        clock_seconds_remaining: int,
        offense_yardline_100_after_play: int,
        transition_type: str,
    ) -> NFLPossessionTransition:
        self._period_clock(period, clock_seconds_remaining)
        yardline = int(offense_yardline_100_after_play)
        if not 0 <= yardline <= 100:
            raise ValueError("TURNOVER_YARDLINE_INVALID")
        if not str(transition_type).strip():
            raise ValueError("TURNOVER_TRANSITION_TYPE_REQUIRED")
        next_yardline = max(1, min(99, 100 - yardline))
        return NFLPossessionTransition(
            transition_index=transition_index,
            transition_type=str(transition_type),
            source_play_id=source_play_id,
            next_drive_id=next_drive_id,
            period=period,
            clock_seconds_remaining=clock_seconds_remaining,
            from_team=offense_team,
            nominal_receiving_team=defense_team,
            next_possession_team=defense_team,
            next_yardline_100=next_yardline,
        )
