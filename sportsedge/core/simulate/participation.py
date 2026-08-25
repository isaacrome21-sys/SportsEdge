"""Player-participation Engine B layered on immutable Engine-A play paths.

Engine B never creates a second score path and never accepts market data. It
assigns player identities to the already-simulated offensive events, then derives
player box-score read-outs that reconcile exactly to Engine A.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from math import isfinite
from typing import Iterable

import numpy as np

from .drive_play import FootballPlayPath


def _validate_shares(rows: Iterable[tuple[str, float]], *, label: str) -> tuple[tuple[str, float], ...]:
    values = tuple((str(player_id).strip(), float(share)) for player_id, share in rows)
    if not values:
        raise ValueError(f"USAGE_SHARES_REQUIRED:{label}")
    player_ids = [player_id for player_id, _ in values]
    if any(not player_id for player_id in player_ids):
        raise ValueError(f"PLAYER_ID_MISSING:{label}")
    if len(set(player_ids)) != len(player_ids):
        raise ValueError(f"PLAYER_ID_DUPLICATE:{label}")
    if any(not isfinite(share) or share < 0.0 for _, share in values):
        raise ValueError(f"USAGE_SHARE_INVALID:{label}")
    if abs(sum(share for _, share in values) - 1.0) > 1e-9:
        raise ValueError(f"USAGE_SHARES_MUST_SUM_TO_ONE:{label}")
    return values


@dataclass(frozen=True)
class TeamPersonnelProfile:
    quarterback_id: str
    rush_shares: tuple[tuple[str, float], ...]
    target_shares: tuple[tuple[str, float], ...]

    def __post_init__(self) -> None:
        quarterback_id = str(self.quarterback_id).strip()
        if not quarterback_id:
            raise ValueError("QUARTERBACK_ID_REQUIRED")
        object.__setattr__(self, "quarterback_id", quarterback_id)
        object.__setattr__(self, "rush_shares", _validate_shares(self.rush_shares, label="rush"))
        object.__setattr__(self, "target_shares", _validate_shares(self.target_shares, label="target"))


@dataclass(frozen=True)
class ParticipationEvent:
    game_id: str
    simulation_id: int
    drive_id: int
    play_id: int
    offense: str
    quarterback_id: str | None = None
    rusher_id: str | None = None
    target_id: str | None = None
    receiver_id: str | None = None


@dataclass
class PlayerBoxScore:
    player_id: str
    team: str
    pass_attempts: int = 0
    completions: int = 0
    passing_yards: int = 0
    passing_tds: int = 0
    interceptions_thrown: int = 0
    rush_attempts: int = 0
    rushing_yards: int = 0
    rushing_tds: int = 0
    targets: int = 0
    receptions: int = 0
    receiving_yards: int = 0
    receiving_tds: int = 0
    longest_completion: int = 0
    longest_rush: int = 0
    longest_reception: int = 0


class EngineBParticipationSimulator:
    """Assign player identities without mutating Engine-A game state."""

    def __init__(
        self,
        *,
        home_team: str,
        away_team: str,
        home_personnel: TeamPersonnelProfile,
        away_personnel: TeamPersonnelProfile,
        seed: int | None = None,
    ) -> None:
        if seed is None:
            raise ValueError("EXPLICIT_SEED_REQUIRED")
        if isinstance(seed, bool) or not isinstance(seed, (int, np.integer)):
            raise ValueError("seed must be an integer")
        if not home_team or not away_team or home_team == away_team:
            raise ValueError("INVALID_TEAM_IDENTITY")
        if not isinstance(home_personnel, TeamPersonnelProfile) or not isinstance(away_personnel, TeamPersonnelProfile):
            raise TypeError("TEAM_PERSONNEL_PROFILE_REQUIRED")
        self.home_team = str(home_team)
        self.away_team = str(away_team)
        self.home_personnel = home_personnel
        self.away_personnel = away_personnel
        self.seed = int(seed)

    def _personnel(self, team: str) -> TeamPersonnelProfile:
        if team == self.home_team:
            return self.home_personnel
        if team == self.away_team:
            return self.away_personnel
        raise ValueError(f"PARTICIPATION_UNKNOWN_TEAM:{team}")

    def _rng(self, path: FootballPlayPath) -> np.random.Generator:
        # Identity-bound and deliberately price-independent.
        payload = f"{self.seed}|{path.game_id}|{path.simulation_id}|ENGINE_B_V1".encode("utf-8")
        derived_seed = int.from_bytes(sha256(payload).digest()[:8], "big", signed=False)
        return np.random.default_rng(derived_seed)

    @staticmethod
    def _choice(rng: np.random.Generator, shares: tuple[tuple[str, float], ...]) -> str:
        ids = [player_id for player_id, _ in shares]
        probs = [share for _, share in shares]
        return ids[int(rng.choice(len(ids), p=probs))]

    def assign(self, path: FootballPlayPath) -> tuple[ParticipationEvent, ...]:
        if path.home_team != self.home_team or path.away_team != self.away_team:
            raise ValueError("PARTICIPATION_PATH_TEAM_MISMATCH")
        rng = self._rng(path)
        rows: list[ParticipationEvent] = []
        for play in path.plays:
            personnel = self._personnel(play.possession)
            quarterback_id: str | None = None
            rusher_id: str | None = None
            target_id: str | None = None
            receiver_id: str | None = None

            if play.play_type == "PASS":
                quarterback_id = personnel.quarterback_id
                target_id = self._choice(rng, personnel.target_shares)
                if play.pass_complete is True:
                    receiver_id = target_id
            elif play.play_type == "RUSH":
                rusher_id = self._choice(rng, personnel.rush_shares)

            rows.append(ParticipationEvent(
                game_id=path.game_id,
                simulation_id=path.simulation_id,
                drive_id=play.drive_id,
                play_id=play.play_id,
                offense=play.possession,
                quarterback_id=quarterback_id,
                rusher_id=rusher_id,
                target_id=target_id,
                receiver_id=receiver_id,
            ))
        validate_participation(path, rows)
        return tuple(rows)


def validate_participation(path: FootballPlayPath, overlay: Iterable[ParticipationEvent]) -> None:
    rows = tuple(overlay)
    if len(rows) != len(path.plays):
        raise ValueError("PARTICIPATION_PLAY_COUNT_MISMATCH")
    for play, part in zip(path.plays, rows):
        if (
            part.game_id != path.game_id
            or part.simulation_id != path.simulation_id
            or part.drive_id != play.drive_id
            or part.play_id != play.play_id
        ):
            raise ValueError("PARTICIPATION_PLAY_IDENTITY_MISMATCH")
        if part.offense != play.possession:
            raise ValueError("PARTICIPATION_OFFENSE_MISMATCH")
        if play.play_type == "PASS":
            if not part.quarterback_id or not part.target_id:
                raise ValueError("PASS_PARTICIPATION_INCOMPLETE")
            if play.pass_complete is True and part.receiver_id != part.target_id:
                raise ValueError("COMPLETION_RECEIVER_TARGET_MISMATCH")
            if play.pass_complete is False and part.receiver_id is not None:
                raise ValueError("INCOMPLETE_PASS_RECEIVER_PRESENT")
        elif play.play_type == "RUSH" and not part.rusher_id:
            raise ValueError("RUSHER_MISSING")


def aggregate_player_box_scores(
    path: FootballPlayPath,
    overlay: Iterable[ParticipationEvent],
) -> dict[tuple[str, str], PlayerBoxScore]:
    parts = tuple(overlay)
    validate_participation(path, parts)
    boxes: dict[tuple[str, str], PlayerBoxScore] = {}

    def get_box(team: str, player_id: str) -> PlayerBoxScore:
        key = (team, player_id)
        if key not in boxes:
            boxes[key] = PlayerBoxScore(player_id=player_id, team=team)
        return boxes[key]

    for play, part in zip(path.plays, parts):
        team = play.possession
        if play.play_type == "PASS":
            qb = get_box(team, str(part.quarterback_id))
            qb.pass_attempts += 1
            if play.turnover_type == "INTERCEPTION":
                qb.interceptions_thrown += 1
            if play.pass_complete is True:
                qb.completions += 1
                qb.passing_yards += int(play.yards)
                qb.longest_completion = max(qb.longest_completion, int(play.yards))
                if play.points == 7:
                    qb.passing_tds += 1

                receiver = get_box(team, str(part.receiver_id))
                receiver.receptions += 1
                receiver.receiving_yards += int(play.yards)
                receiver.longest_reception = max(receiver.longest_reception, int(play.yards))
                if play.points == 7:
                    receiver.receiving_tds += 1

            target = get_box(team, str(part.target_id))
            target.targets += 1

        elif play.play_type == "RUSH":
            rusher = get_box(team, str(part.rusher_id))
            rusher.rush_attempts += 1
            rusher.rushing_yards += int(play.yards)
            rusher.longest_rush = max(rusher.longest_rush, int(play.yards))
            if play.points == 7:
                rusher.rushing_tds += 1

    pass_yards = sum(
        play.yards for play in path.plays
        if play.play_type == "PASS" and play.pass_complete is True
    )
    if sum(box.passing_yards for box in boxes.values()) != pass_yards:
        raise ValueError("PARTICIPATION_PASS_YARDS_RECONCILIATION_FAILED")
    if sum(box.receiving_yards for box in boxes.values()) != pass_yards:
        raise ValueError("PARTICIPATION_RECEIVING_YARDS_RECONCILIATION_FAILED")
    rush_yards = sum(play.yards for play in path.plays if play.play_type == "RUSH")
    if sum(box.rushing_yards for box in boxes.values()) != rush_yards:
        raise ValueError("PARTICIPATION_RUSH_YARDS_RECONCILIATION_FAILED")
    offensive_touchdowns = sum(play.points == 7 for play in path.plays)
    attributed_touchdowns = sum(box.rushing_tds + box.receiving_tds for box in boxes.values())
    if attributed_touchdowns != offensive_touchdowns:
        raise ValueError("PARTICIPATION_TOUCHDOWN_RECONCILIATION_FAILED")
    return boxes
