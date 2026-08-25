"""Football Engine-B participation overlay on immutable Engine-A play paths.

Engine B never creates a second game path or changes points.  It assigns the
quarterback/rusher/target/receiver identities to the already-created Engine-A
plays from point-in-time personnel usage profiles, then derives reconciled
player box scores from that same event stream.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from math import isfinite
from typing import Iterable

import numpy as np

from sportsedge.core.simulate.football_path import GamePath, PlayEvent


def _validated_shares(rows: Iterable[tuple[str, float]], *, name: str) -> tuple[tuple[str, float], ...]:
    values = tuple((str(player).strip(), float(share)) for player, share in rows)
    if not values:
        raise ValueError(f"USAGE_SHARES_REQUIRED:{name}")
    ids = [player for player, _ in values]
    if any(not player for player in ids):
        raise ValueError(f"PLAYER_ID_MISSING:{name}")
    if len(set(ids)) != len(ids):
        raise ValueError(f"PLAYER_ID_DUPLICATE:{name}")
    if any(not isfinite(share) or share < 0.0 for _, share in values):
        raise ValueError(f"USAGE_SHARE_INVALID:{name}")
    total = sum(share for _, share in values)
    if abs(total - 1.0) > 1e-9:
        raise ValueError(f"USAGE_SHARES_MUST_SUM_TO_ONE:{name}")
    return values


@dataclass(frozen=True)
class TeamPersonnelProfile:
    quarterback_id: str
    rush_shares: tuple[tuple[str, float], ...]
    target_shares: tuple[tuple[str, float], ...]

    def __post_init__(self) -> None:
        qb = str(self.quarterback_id).strip()
        if not qb:
            raise ValueError("QUARTERBACK_ID_REQUIRED")
        object.__setattr__(self, "quarterback_id", qb)
        object.__setattr__(self, "rush_shares", _validated_shares(self.rush_shares, name="rush"))
        object.__setattr__(self, "target_shares", _validated_shares(self.target_shares, name="target"))


@dataclass(frozen=True)
class ParticipationEvent:
    game_id: str
    simulation_id: int
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
    interceptions: int = 0
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


class FootballParticipationEngine:
    def __init__(
        self,
        *,
        home_team: str,
        away_team: str,
        home_personnel: TeamPersonnelProfile,
        away_personnel: TeamPersonnelProfile,
        seed: int,
    ) -> None:
        if not str(home_team).strip() or not str(away_team).strip():
            raise ValueError("TEAM_ID_REQUIRED")
        if str(home_team) == str(away_team):
            raise ValueError("HOME_AWAY_TEAM_COLLISION")
        if isinstance(seed, bool) or not isinstance(seed, (int, np.integer)):
            raise ValueError("EXPLICIT_INTEGER_SEED_REQUIRED")
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

    def _rng_for(self, path: GamePath) -> np.random.Generator:
        identity = f"{self.seed}|{path.game_id}|{path.simulation_id}|ENGINE_B_V1".encode("utf-8")
        derived = int.from_bytes(sha256(identity).digest()[:8], "big", signed=False)
        return np.random.default_rng(derived)

    @staticmethod
    def _choose(rng: np.random.Generator, rows: tuple[tuple[str, float], ...]) -> str:
        ids = [player for player, _ in rows]
        probs = [share for _, share in rows]
        return ids[int(rng.choice(len(ids), p=probs))]

    def assign(self, path: GamePath) -> tuple[ParticipationEvent, ...]:
        if path.home_team != self.home_team or path.away_team != self.away_team:
            raise ValueError("PARTICIPATION_PATH_TEAM_MISMATCH")
        rng = self._rng_for(path)
        out: list[ParticipationEvent] = []
        for play in path.plays:
            personnel = self._personnel(play.possession)
            qb: str | None = None
            rusher: str | None = None
            target: str | None = None
            receiver: str | None = None
            if play.play_type in {"PASS_COMPLETE", "PASS_INCOMPLETE", "INTERCEPTION", "SACK"}:
                qb = personnel.quarterback_id
            if play.play_type in {"PASS_COMPLETE", "PASS_INCOMPLETE", "INTERCEPTION"}:
                target = self._choose(rng, personnel.target_shares)
            if play.play_type == "PASS_COMPLETE":
                receiver = target
            if play.play_type == "RUSH":
                rusher = self._choose(rng, personnel.rush_shares)
            out.append(ParticipationEvent(
                game_id=play.game_id,
                simulation_id=play.simulation_id,
                play_id=play.play_id,
                offense=play.possession,
                quarterback_id=qb,
                rusher_id=rusher,
                target_id=target,
                receiver_id=receiver,
            ))
        validate_participation(path, out)
        return tuple(out)


def validate_participation(path: GamePath, overlay: Iterable[ParticipationEvent]) -> None:
    rows = tuple(overlay)
    if len(rows) != len(path.plays):
        raise ValueError("PARTICIPATION_PLAY_COUNT_MISMATCH")
    for play, part in zip(path.plays, rows):
        if (part.game_id, part.simulation_id, part.play_id) != (play.game_id, play.simulation_id, play.play_id):
            raise ValueError("PARTICIPATION_PLAY_IDENTITY_MISMATCH")
        if part.offense != play.possession:
            raise ValueError("PARTICIPATION_OFFENSE_MISMATCH")
        if play.play_type in {"PASS_COMPLETE", "PASS_INCOMPLETE", "INTERCEPTION", "SACK"} and not part.quarterback_id:
            raise ValueError("PARTICIPATION_QB_MISSING")
        if play.play_type in {"PASS_COMPLETE", "PASS_INCOMPLETE", "INTERCEPTION"} and not part.target_id:
            raise ValueError("PARTICIPATION_TARGET_MISSING")
        if play.play_type == "PASS_COMPLETE" and part.receiver_id != part.target_id:
            raise ValueError("PARTICIPATION_RECEIVER_TARGET_MISMATCH")
        if play.play_type == "RUSH" and not part.rusher_id:
            raise ValueError("PARTICIPATION_RUSHER_MISSING")


def aggregate_player_box_scores(
    path: GamePath,
    overlay: Iterable[ParticipationEvent],
) -> dict[tuple[str, str], PlayerBoxScore]:
    parts = tuple(overlay)
    validate_participation(path, parts)
    boxes: dict[tuple[str, str], PlayerBoxScore] = {}

    def box(team: str, player_id: str) -> PlayerBoxScore:
        key = (team, player_id)
        if key not in boxes:
            boxes[key] = PlayerBoxScore(player_id=player_id, team=team)
        return boxes[key]

    for play, part in zip(path.plays, parts):
        team = play.possession
        if play.play_type in {"PASS_COMPLETE", "PASS_INCOMPLETE", "INTERCEPTION"}:
            qb = box(team, str(part.quarterback_id))
            qb.pass_attempts += 1
            if play.play_type == "PASS_COMPLETE":
                qb.completions += 1
                qb.passing_yards += int(play.yards)
                qb.longest_completion = max(qb.longest_completion, int(play.yards))
                if play.drive_terminal == "TOUCHDOWN" and play.scoring_team == team:
                    qb.passing_tds += 1
            elif play.play_type == "INTERCEPTION":
                qb.interceptions += 1

            target = box(team, str(part.target_id))
            target.targets += 1
            if play.play_type == "PASS_COMPLETE":
                target.receptions += 1
                target.receiving_yards += int(play.yards)
                target.longest_reception = max(target.longest_reception, int(play.yards))
                if play.drive_terminal == "TOUCHDOWN" and play.scoring_team == team:
                    target.receiving_tds += 1

        elif play.play_type == "RUSH":
            rusher = box(team, str(part.rusher_id))
            rusher.rush_attempts += 1
            rusher.rushing_yards += int(play.yards)
            rusher.longest_rush = max(rusher.longest_rush, int(play.yards))
            if play.drive_terminal == "TOUCHDOWN" and play.scoring_team == team:
                rusher.rushing_tds += 1

    # Structural reconciliation: every completed-pass yard belongs once to the
    # quarterback and once to a receiver; every rush yard belongs once to a
    # rusher. These are different statistical ledgers, not double-counted team
    # yards.
    pass_path = sum(p.yards for p in path.plays if p.play_type == "PASS_COMPLETE")
    pass_boxes = sum(b.passing_yards for b in boxes.values())
    receiving_boxes = sum(b.receiving_yards for b in boxes.values())
    rush_path = sum(p.yards for p in path.plays if p.play_type == "RUSH")
    rush_boxes = sum(b.rushing_yards for b in boxes.values())
    if pass_boxes != pass_path or receiving_boxes != pass_path:
        raise ValueError("PARTICIPATION_PASS_YARD_RECONCILIATION_FAILED")
    if rush_boxes != rush_path:
        raise ValueError("PARTICIPATION_RUSH_YARD_RECONCILIATION_FAILED")
    offensive_tds = sum(
        p.drive_terminal == "TOUCHDOWN" and p.scoring_team == p.possession for p in path.plays
    )
    attributed_tds = sum(b.rushing_tds + b.receiving_tds for b in boxes.values())
    if attributed_tds != offensive_tds:
        raise ValueError("PARTICIPATION_TOUCHDOWN_RECONCILIATION_FAILED")
    return boxes
