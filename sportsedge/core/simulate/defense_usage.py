"""Engine B defensive participation and attribution over Engine A play paths.

Defensive statistics are identities attached to football events that already
exist on the Engine A path. This layer never creates an independent sack,
interception, tackle, or turnover count. Unresolved participation fails closed.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .drive_play import FootballPlayPath, PlayEvent


@dataclass(frozen=True)
class DefenderUsageProfile:
    player_id: str
    team: str
    position: str
    active: bool | None
    snap_share: float
    tackle_share: float
    assist_share: float
    sack_share: float
    interception_share: float

    def __post_init__(self) -> None:
        if not str(self.player_id).strip():
            raise ValueError("DEFENDER_ID_REQUIRED")
        if not str(self.team).strip():
            raise ValueError("DEFENDER_TEAM_REQUIRED")
        if not str(self.position).strip():
            raise ValueError("DEFENDER_POSITION_REQUIRED")
        if self.active is not None and not isinstance(self.active, bool):
            raise ValueError("DEFENDER_ACTIVE_STATE_INVALID")
        for name in (
            "snap_share",
            "tackle_share",
            "assist_share",
            "sack_share",
            "interception_share",
        ):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"DEFENDER_USAGE_SHARE_OUT_OF_RANGE:{name}")


@dataclass(frozen=True)
class TeamDefenseUsageProfile:
    team: str
    players: tuple[DefenderUsageProfile, ...]
    assist_probability: float = 0.45

    def __post_init__(self) -> None:
        if not str(self.team).strip():
            raise ValueError("TEAM_DEFENSE_TEAM_REQUIRED")
        if not self.players:
            raise ValueError("TEAM_DEFENSE_PLAYERS_REQUIRED")
        ids = [player.player_id for player in self.players]
        if len(ids) != len(set(ids)):
            raise ValueError("DUPLICATE_DEFENDER_USAGE_ID")
        if any(player.team != self.team for player in self.players):
            raise ValueError("DEFENDER_USAGE_TEAM_MISMATCH")
        if not 0.0 <= float(self.assist_probability) <= 1.0:
            raise ValueError("DEFENSE_ASSIST_PROBABILITY_OUT_OF_RANGE")

    def player(self, player_id: str) -> DefenderUsageProfile:
        for player in self.players:
            if player.player_id == player_id:
                return player
        raise KeyError(player_id)


@dataclass(frozen=True)
class AttributedDefensivePlay:
    base_play: PlayEvent
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
                raise ValueError("ATTRIBUTED_DEFENDER_NOT_ACTIVE")
        if self.primary_tackler_id is not None and self.primary_tackler_id == self.assist_tackler_id:
            raise ValueError("PRIMARY_AND_ASSIST_TACKLER_COLLISION")

        if self.base_play.play_type.upper() == "SACK":
            if self.sack_player_id is None:
                raise ValueError("SACK_DEFENDER_ATTRIBUTION_REQUIRED")
            if self.primary_tackler_id != self.sack_player_id:
                raise ValueError("SACK_PRIMARY_TACKLER_MISMATCH")
        elif self.sack_player_id is not None:
            raise ValueError("NON_SACK_HAS_SACK_DEFENDER")

        if self.base_play.turnover_type == "INTERCEPTION":
            if self.interceptor_id is None:
                raise ValueError("INTERCEPTOR_ATTRIBUTION_REQUIRED")
        elif self.interceptor_id is not None:
            raise ValueError("NON_INTERCEPTION_HAS_INTERCEPTOR")

        tackle_eligible = _tackle_eligible(self.base_play)
        if tackle_eligible and self.primary_tackler_id is None:
            raise ValueError("PRIMARY_TACKLER_ATTRIBUTION_REQUIRED")
        if not tackle_eligible and (
            self.primary_tackler_id is not None or self.assist_tackler_id is not None
        ):
            raise ValueError("NON_TACKLE_PLAY_HAS_TACKLE_ATTRIBUTION")


def _tackle_eligible(play: PlayEvent) -> bool:
    play_type = play.play_type.upper()
    if play_type == "SACK":
        return True
    if play_type == "RUSH":
        return play.score_type != "TOUCHDOWN_CANDIDATE"
    if play_type == "PASS":
        return play.pass_complete is True and play.score_type != "TOUCHDOWN_CANDIDATE"
    return False


def _blank_player_stats() -> dict[str, int]:
    return {
        "sacks": 0,
        "solo_tackles": 0,
        "assists": 0,
        "tackles_assists": 0,
        "interceptions": 0,
    }


@dataclass(frozen=True)
class AttributedDefensivePath:
    base_path: FootballPlayPath
    home_defense: TeamDefenseUsageProfile
    away_defense: TeamDefenseUsageProfile
    plays: tuple[AttributedDefensivePlay, ...]

    def __post_init__(self) -> None:
        if self.home_defense.team != self.base_path.home_team:
            raise ValueError("HOME_DEFENSE_TEAM_MISMATCH")
        if self.away_defense.team != self.base_path.away_team:
            raise ValueError("AWAY_DEFENSE_TEAM_MISMATCH")
        if len(self.plays) != len(self.base_path.plays):
            raise ValueError("DEFENSIVE_ATTRIBUTED_PLAY_COUNT_MISMATCH")
        for base, attributed in zip(self.base_path.plays, self.plays):
            if base != attributed.base_play:
                raise ValueError("DEFENSIVE_ATTRIBUTED_BASE_PLAY_MISMATCH")
            expected_defense = (
                self.base_path.away_team
                if base.possession == self.base_path.home_team
                else self.base_path.home_team
            )
            if attributed.defense_team != expected_defense:
                raise ValueError("DEFENSIVE_ATTRIBUTED_TEAM_MISMATCH")

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
        out: dict[str, dict[str, int]] = {}
        for profile in (self.home_defense, self.away_defense):
            ids = {row.player_id for row in profile.players}
            offense_team = (
                self.base_path.away_team
                if profile.team == self.base_path.home_team
                else self.base_path.home_team
            )
            opponent_plays = [
                play for play in self.base_path.plays if play.possession == offense_team
            ]
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
        for profile in (self.home_defense, self.away_defense):
            offense_team = (
                self.base_path.away_team
                if profile.team == self.base_path.home_team
                else self.base_path.home_team
            )
            opponent_plays = [
                play for play in self.base_path.plays if play.possession == offense_team
            ]
            expected_sacks = sum(play.play_type.upper() == "SACK" for play in opponent_plays)
            expected_ints = sum(play.turnover_type == "INTERCEPTION" for play in opponent_plays)
            expected_turnovers = sum(
                play.turnover_type in {"INTERCEPTION", "FUMBLE"}
                for play in opponent_plays
            )
            expected_primary_tackles = sum(_tackle_eligible(play) for play in opponent_plays)
            ids = {row.player_id for row in profile.players}
            rows = [player[player_id] for player_id in ids]

            if team[profile.team]["team_sacks"] != expected_sacks:
                raise ValueError("TEAM_SACK_RECONCILIATION_FAILED")
            if sum(row["interceptions"] for row in rows) != expected_ints:
                raise ValueError("DEFENDER_INTERCEPTION_RECONCILIATION_FAILED")
            if team[profile.team]["team_turnovers"] != expected_turnovers:
                raise ValueError("TEAM_TURNOVER_RECONCILIATION_FAILED")
            if sum(row["solo_tackles"] for row in rows) != expected_primary_tackles:
                raise ValueError("PRIMARY_TACKLE_RECONCILIATION_FAILED")
            if any(row["tackles_assists"] != row["solo_tackles"] + row["assists"] for row in rows):
                raise ValueError("TACKLE_ASSIST_SUM_RECONCILIATION_FAILED")


class EngineBDefenseAllocator:
    """Seeded defender-identity allocator over one Engine A play path."""

    def __init__(
        self,
        home_defense: TeamDefenseUsageProfile,
        away_defense: TeamDefenseUsageProfile,
        *,
        seed: int | None = None,
    ) -> None:
        if seed is None:
            raise ValueError("EXPLICIT_SEED_REQUIRED")
        if isinstance(seed, bool) or not isinstance(seed, (int, np.integer)):
            raise ValueError("seed must be an integer")
        if not isinstance(home_defense, TeamDefenseUsageProfile) or not isinstance(away_defense, TeamDefenseUsageProfile):
            raise TypeError("TEAM_DEFENSE_USAGE_PROFILE_REQUIRED")
        if home_defense.team == away_defense.team:
            raise ValueError("DEFENSE_HOME_AWAY_TEAM_COLLISION")
        self.home_defense = home_defense
        self.away_defense = away_defense
        self.seed = int(seed)
        self.rng = np.random.default_rng(self.seed)

    @staticmethod
    def _assert_resolved(profile: TeamDefenseUsageProfile) -> None:
        for player in profile.players:
            if player.active is None:
                raise ValueError(f"DEFENDER_PARTICIPATION_UNRESOLVED:{player.player_id}")

    def _active_set(self, profile: TeamDefenseUsageProfile) -> list[DefenderUsageProfile]:
        active = [
            player
            for player in profile.players
            if player.active is True and self.rng.random() < player.snap_share
        ]
        return active

    def _weighted_pick(
        self,
        profile: TeamDefenseUsageProfile,
        active: list[DefenderUsageProfile],
        *,
        weight_name: str,
        exclude: set[str] | None = None,
    ) -> tuple[DefenderUsageProfile, bool]:
        excluded = exclude or set()
        candidates = [
            player for player in active
            if player.player_id not in excluded and float(getattr(player, weight_name)) > 0
        ]
        fallback = False
        if not candidates:
            candidates = [
                player for player in profile.players
                if player.active is True
                and player.player_id not in excluded
                and float(getattr(player, weight_name)) > 0
            ]
            fallback = True
        if not candidates:
            raise ValueError(f"DEFENSE_ALLOCATION_WEIGHT_ZERO:{weight_name}")
        weights = np.asarray([float(getattr(player, weight_name)) for player in candidates], dtype=float)
        weights = weights / weights.sum()
        return candidates[int(self.rng.choice(len(candidates), p=weights))], fallback

    def attribute(self, path: FootballPlayPath) -> AttributedDefensivePath:
        if not isinstance(path, FootballPlayPath):
            raise TypeError("FOOTBALL_PLAY_PATH_REQUIRED")
        if path.home_team != self.home_defense.team or path.away_team != self.away_defense.team:
            raise ValueError("DEFENSE_USAGE_PATH_TEAM_MISMATCH")
        self._assert_resolved(self.home_defense)
        self._assert_resolved(self.away_defense)

        out: list[AttributedDefensivePlay] = []
        for play in path.plays:
            profile = (
                self.away_defense
                if play.possession == path.home_team
                else self.home_defense
            )
            active = self._active_set(profile)
            active_ids = {player.player_id for player in active}
            primary: str | None = None
            assist: str | None = None
            sacker: str | None = None
            interceptor: str | None = None
            fallback = False

            if play.play_type.upper() == "SACK":
                chosen, used_fallback = self._weighted_pick(
                    profile, active, weight_name="sack_share"
                )
                sacker = chosen.player_id
                primary = sacker
                active_ids.add(sacker)
                fallback = fallback or used_fallback
            elif _tackle_eligible(play):
                chosen, used_fallback = self._weighted_pick(
                    profile, active, weight_name="tackle_share"
                )
                primary = chosen.player_id
                active_ids.add(primary)
                fallback = fallback or used_fallback

            if primary is not None and self.rng.random() < profile.assist_probability:
                try:
                    chosen, used_fallback = self._weighted_pick(
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
                    fallback = fallback or used_fallback

            if play.turnover_type == "INTERCEPTION":
                chosen, used_fallback = self._weighted_pick(
                    profile, active, weight_name="interception_share"
                )
                interceptor = chosen.player_id
                active_ids.add(interceptor)
                fallback = fallback or used_fallback

            out.append(
                AttributedDefensivePlay(
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

        result = AttributedDefensivePath(
            base_path=path,
            home_defense=self.home_defense,
            away_defense=self.away_defense,
            plays=tuple(out),
        )
        result.assert_reconciliation()
        return result

    def attribute_many(self, paths: list[FootballPlayPath]) -> list[AttributedDefensivePath]:
        return [self.attribute(path) for path in paths]
