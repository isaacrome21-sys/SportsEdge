"""Full-game Engine B defensive attribution across regulation and overtime.

Regulation and overtime retain their native Engine A event types. This module
only allocates defender identity to events that already exist, then combines the
two periods into one sportsbook-facing full-game defensive stat ledger.
"""

from __future__ import annotations

from dataclasses import dataclass

from .defense_usage import (
    AttributedDefensivePath,
    DefenderUsageProfile,
    EngineBDefenseAllocator,
    TeamDefenseUsageProfile,
    _blank_player_stats,
)
from .overtime_simulator import NFLRegularSeasonOTPlay, NFLRegularSeasonOTSimulation


def _ot_tackle_eligible(play: NFLRegularSeasonOTPlay) -> bool:
    play_type = play.play_type.upper()
    if play_type == "SACK":
        return True
    if play_type == "RUSH":
        return play.raw_points == 0
    if play_type == "PASS":
        return play.pass_complete is True and play.raw_points == 0
    return False


@dataclass(frozen=True)
class AttributedOTDefensivePlay:
    base_play: NFLRegularSeasonOTPlay
    defense_team: str
    active_player_ids: tuple[str, ...]
    primary_tackler_id: str | None = None
    assist_tackler_id: str | None = None
    sack_player_id: str | None = None
    interceptor_id: str | None = None
    allocation_fallback: bool = False

    def __post_init__(self) -> None:
        active = set(self.active_player_ids)
        for player_id in (
            self.primary_tackler_id,
            self.assist_tackler_id,
            self.sack_player_id,
            self.interceptor_id,
        ):
            if player_id is not None and player_id not in active:
                raise ValueError("OT_ATTRIBUTED_DEFENDER_NOT_ACTIVE")
        if self.primary_tackler_id is not None and self.primary_tackler_id == self.assist_tackler_id:
            raise ValueError("OT_PRIMARY_AND_ASSIST_TACKLER_COLLISION")
        if self.base_play.play_type.upper() == "SACK":
            if self.sack_player_id is None:
                raise ValueError("OT_SACK_DEFENDER_ATTRIBUTION_REQUIRED")
            if self.primary_tackler_id != self.sack_player_id:
                raise ValueError("OT_SACK_PRIMARY_TACKLER_MISMATCH")
        elif self.sack_player_id is not None:
            raise ValueError("OT_NON_SACK_HAS_SACK_DEFENDER")
        if self.base_play.turnover_type == "INTERCEPTION":
            if self.interceptor_id is None:
                raise ValueError("OT_INTERCEPTOR_ATTRIBUTION_REQUIRED")
        elif self.interceptor_id is not None:
            raise ValueError("OT_NON_INTERCEPTION_HAS_INTERCEPTOR")
        tackle_eligible = _ot_tackle_eligible(self.base_play)
        if tackle_eligible and self.primary_tackler_id is None:
            raise ValueError("OT_PRIMARY_TACKLER_ATTRIBUTION_REQUIRED")
        if not tackle_eligible and (
            self.primary_tackler_id is not None or self.assist_tackler_id is not None
        ):
            raise ValueError("OT_NON_TACKLE_PLAY_HAS_TACKLE_ATTRIBUTION")


@dataclass(frozen=True)
class AttributedOvertimeDefensivePath:
    base_simulation: NFLRegularSeasonOTSimulation
    home_defense: TeamDefenseUsageProfile
    away_defense: TeamDefenseUsageProfile
    plays: tuple[AttributedOTDefensivePlay, ...]

    @property
    def game_id(self) -> str:
        return self.base_simulation.regulation_path.base_path.game_id

    def __post_init__(self) -> None:
        home = self.base_simulation.regulation_path.base_path.home_team
        away = self.base_simulation.regulation_path.base_path.away_team
        if self.home_defense.team != home or self.away_defense.team != away:
            raise ValueError("OT_DEFENSE_TEAM_MISMATCH")
        if len(self.plays) != len(self.base_simulation.plays):
            raise ValueError("OT_DEFENSIVE_ATTRIBUTED_PLAY_COUNT_MISMATCH")
        for base, attributed in zip(self.base_simulation.plays, self.plays):
            if base != attributed.base_play:
                raise ValueError("OT_DEFENSIVE_ATTRIBUTED_BASE_PLAY_MISMATCH")
            expected_defense = away if base.opportunity_team == home else home
            if attributed.defense_team != expected_defense:
                raise ValueError("OT_DEFENSIVE_ATTRIBUTED_TEAM_MISMATCH")

    def player_stats(self) -> dict[str, dict[str, int]]:
        stats = {
            player.player_id: _blank_player_stats()
            for profile in (self.home_defense, self.away_defense)
            for player in profile.players
        }
        for attributed in self.plays:
            if attributed.primary_tackler_id is not None:
                stats[attributed.primary_tackler_id]["solo_tackles"] += 1
            if attributed.assist_tackler_id is not None:
                stats[attributed.assist_tackler_id]["assists"] += 1
            if attributed.sack_player_id is not None:
                stats[attributed.sack_player_id]["sacks"] += 1
            if attributed.interceptor_id is not None:
                stats[attributed.interceptor_id]["interceptions"] += 1
        for row in stats.values():
            row["tackles_assists"] = row["solo_tackles"] + row["assists"]
        return stats

    def team_stats(self) -> dict[str, dict[str, int]]:
        player = self.player_stats()
        home = self.base_simulation.regulation_path.base_path.home_team
        away = self.base_simulation.regulation_path.base_path.away_team
        out: dict[str, dict[str, int]] = {}
        for profile in (self.home_defense, self.away_defense):
            ids = {row.player_id for row in profile.players}
            offense = away if profile.team == home else home
            opponent_plays = [play for play in self.base_simulation.plays if play.opportunity_team == offense]
            out[profile.team] = {
                "team_sacks": sum(player[player_id]["sacks"] for player_id in ids),
                "team_turnovers": sum(
                    play.turnover_type in {"INTERCEPTION", "FUMBLE"}
                    for play in opponent_plays
                ),
            }
        return out

    def assert_reconciliation(self) -> None:
        player = self.player_stats()
        team = self.team_stats()
        home = self.base_simulation.regulation_path.base_path.home_team
        away = self.base_simulation.regulation_path.base_path.away_team
        for profile in (self.home_defense, self.away_defense):
            offense = away if profile.team == home else home
            opponent_plays = [play for play in self.base_simulation.plays if play.opportunity_team == offense]
            ids = {row.player_id for row in profile.players}
            rows = [player[player_id] for player_id in ids]
            expected_sacks = sum(play.play_type.upper() == "SACK" for play in opponent_plays)
            expected_ints = sum(play.turnover_type == "INTERCEPTION" for play in opponent_plays)
            expected_turnovers = sum(play.turnover_type in {"INTERCEPTION", "FUMBLE"} for play in opponent_plays)
            expected_primary = sum(_ot_tackle_eligible(play) for play in opponent_plays)
            if team[profile.team]["team_sacks"] != expected_sacks:
                raise ValueError("OT_TEAM_SACK_RECONCILIATION_FAILED")
            if sum(row["interceptions"] for row in rows) != expected_ints:
                raise ValueError("OT_DEFENDER_INTERCEPTION_RECONCILIATION_FAILED")
            if team[profile.team]["team_turnovers"] != expected_turnovers:
                raise ValueError("OT_TEAM_TURNOVER_RECONCILIATION_FAILED")
            if sum(row["solo_tackles"] for row in rows) != expected_primary:
                raise ValueError("OT_PRIMARY_TACKLE_RECONCILIATION_FAILED")


class EngineBOvertimeDefenseAllocator:
    """Allocate defender identity to existing OT Engine A events only."""

    def __init__(
        self,
        home_defense: TeamDefenseUsageProfile,
        away_defense: TeamDefenseUsageProfile,
        *,
        seed: int | None = None,
    ) -> None:
        self._allocator = EngineBDefenseAllocator(
            home_defense,
            away_defense,
            seed=seed,
        )
        self.home_defense = home_defense
        self.away_defense = away_defense

    def attribute(self, simulation: NFLRegularSeasonOTSimulation) -> AttributedOvertimeDefensivePath:
        if not isinstance(simulation, NFLRegularSeasonOTSimulation):
            raise TypeError("NFL_OVERTIME_SIMULATION_REQUIRED")
        home = simulation.regulation_path.base_path.home_team
        away = simulation.regulation_path.base_path.away_team
        if home != self.home_defense.team or away != self.away_defense.team:
            raise ValueError("OT_DEFENSE_USAGE_PATH_TEAM_MISMATCH")
        self._allocator._assert_resolved(self.home_defense)
        self._allocator._assert_resolved(self.away_defense)

        out: list[AttributedOTDefensivePlay] = []
        for play in simulation.plays:
            profile = self.away_defense if play.opportunity_team == home else self.home_defense
            active = self._allocator._active_set(profile)
            active_ids = {player.player_id for player in active}
            primary = assist = sacker = interceptor = None
            fallback = False

            if play.play_type.upper() == "SACK":
                chosen, used = self._allocator._weighted_pick(profile, active, weight_name="sack_share")
                sacker = chosen.player_id
                primary = sacker
                active_ids.add(sacker)
                fallback = fallback or used
            elif _ot_tackle_eligible(play):
                chosen, used = self._allocator._weighted_pick(profile, active, weight_name="tackle_share")
                primary = chosen.player_id
                active_ids.add(primary)
                fallback = fallback or used

            if primary is not None and self._allocator.rng.random() < profile.assist_probability:
                try:
                    chosen, used = self._allocator._weighted_pick(
                        profile,
                        active,
                        weight_name="assist_share",
                        exclude={primary},
                    )
                except ValueError as exc:
                    if "DEFENSE_ALLOCATION_WEIGHT_ZERO:assist_share" not in str(exc):
                        raise
                else:
                    assist = chosen.player_id
                    active_ids.add(assist)
                    fallback = fallback or used

            if play.turnover_type == "INTERCEPTION":
                chosen, used = self._allocator._weighted_pick(profile, active, weight_name="interception_share")
                interceptor = chosen.player_id
                active_ids.add(interceptor)
                fallback = fallback or used

            out.append(
                AttributedOTDefensivePlay(
                    base_play=play,
                    defense_team=profile.team,
                    active_player_ids=tuple(sorted(active_ids)),
                    primary_tackler_id=primary,
                    assist_tackler_id=assist,
                    sack_player_id=sacker,
                    interceptor_id=interceptor,
                    allocation_fallback=fallback,
                )
            )

        result = AttributedOvertimeDefensivePath(
            base_simulation=simulation,
            home_defense=self.home_defense,
            away_defense=self.away_defense,
            plays=tuple(out),
        )
        result.assert_reconciliation()
        return result


@dataclass(frozen=True)
class FullGameDefensivePath:
    regulation: AttributedDefensivePath
    overtime: AttributedOvertimeDefensivePath | None = None

    @property
    def base_path(self):
        return self.regulation.base_path

    @property
    def home_defense(self) -> TeamDefenseUsageProfile:
        return self.regulation.home_defense

    @property
    def away_defense(self) -> TeamDefenseUsageProfile:
        return self.regulation.away_defense

    def __post_init__(self) -> None:
        if self.overtime is not None:
            if self.overtime.base_simulation.regulation_path.base_path != self.regulation.base_path:
                raise ValueError("FULL_GAME_DEFENSE_REGULATION_OT_PATH_MISMATCH")
            if self.overtime.home_defense != self.regulation.home_defense or self.overtime.away_defense != self.regulation.away_defense:
                raise ValueError("FULL_GAME_DEFENSE_USAGE_MISMATCH")

    def player_stats(self) -> dict[str, dict[str, int]]:
        out = {player_id: dict(row) for player_id, row in self.regulation.player_stats().items()}
        if self.overtime is not None:
            for player_id, row in self.overtime.player_stats().items():
                for stat in ("sacks", "solo_tackles", "assists", "interceptions"):
                    out[player_id][stat] += row[stat]
                out[player_id]["tackles_assists"] = out[player_id]["solo_tackles"] + out[player_id]["assists"]
        return out

    def team_stats(self) -> dict[str, dict[str, int]]:
        out = {team: dict(row) for team, row in self.regulation.team_stats().items()}
        if self.overtime is not None:
            for team, row in self.overtime.team_stats().items():
                out[team]["team_sacks"] += row["team_sacks"]
                out[team]["team_turnovers"] += row["team_turnovers"]
        return out

    def assert_reconciliation(self) -> None:
        self.regulation.assert_reconciliation()
        if self.overtime is not None:
            self.overtime.assert_reconciliation()
        player = self.player_stats()
        team = self.team_stats()
        for profile in (self.home_defense, self.away_defense):
            ids = {row.player_id for row in profile.players}
            if sum(player[player_id]["sacks"] for player_id in ids) != team[profile.team]["team_sacks"]:
                raise ValueError("FULL_GAME_TEAM_SACK_RECONCILIATION_FAILED")
            if any(player[player_id]["tackles_assists"] != player[player_id]["solo_tackles"] + player[player_id]["assists"] for player_id in ids):
                raise ValueError("FULL_GAME_TACKLE_ASSIST_RECONCILIATION_FAILED")
