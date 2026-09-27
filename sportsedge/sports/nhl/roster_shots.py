"""Coherent roster-level NHL shots-on-goal allocation.

Callers supply a team SOG path and PIT-safe/versioned player workload weights.
Every simulated team shot is assigned to exactly one active skater, so player SOG
props share one team environment instead of independent Poisson draws.
"""
from dataclasses import dataclass
import hashlib
import math
import random


@dataclass(frozen=True)
class NHLRosterShotRole:
    player_id: str
    team: str
    captured_at: str
    source: str
    version: str
    shot_weight: float
    lineup_status: str

    def validate(self) -> None:
        if not all((self.player_id, self.captured_at, self.source, self.version)):
            raise ValueError("identity/provenance required")
        if self.team not in {"HOME", "AWAY"}:
            raise ValueError("team must be HOME or AWAY")
        if self.lineup_status not in {"CONFIRMED", "PROJECTED"}:
            raise ValueError("invalid lineup status")
        if not math.isfinite(self.shot_weight) or self.shot_weight < 0:
            raise ValueError("shot weight must be finite and nonnegative")


@dataclass(frozen=True)
class NHLRosterShotPaths:
    shots: dict[str, tuple[int, ...]]
    team_shots: tuple[int, ...]
    seed: int
    version: str


def _pick(rng: random.Random, roles: list[NHLRosterShotRole]) -> NHLRosterShotRole:
    total = sum(r.shot_weight for r in roles)
    if total <= 0:
        raise ValueError("positive roster shot weight required")
    target = rng.random() * total
    acc = 0.0
    for role in roles:
        acc += role.shot_weight
        if target <= acc:
            return role
    return roles[-1]


def simulate_roster_shots(
    team_shots: tuple[int, ...], roles: list[NHLRosterShotRole], *, team: str,
    version: str, game_seed: int, seed: int | None = None,
) -> NHLRosterShotPaths:
    if not team_shots or not roles or not version:
        raise ValueError("team shot paths, roster and version required")
    if any((not isinstance(x, int)) or x < 0 for x in team_shots):
        raise ValueError("team shots must be nonnegative integers")
    if any(r.team != team for r in roles):
        raise ValueError("mixed-team roster")
    if len({r.player_id for r in roles}) != len(roles):
        raise ValueError("duplicate player")
    for role in roles:
        role.validate()
    if sum(r.shot_weight for r in roles) <= 0:
        raise ValueError("positive roster shot weight required")
    if seed is None:
        signature = "|".join(
            f"{r.player_id}:{r.version}:{r.shot_weight:.12g}"
            for r in sorted(roles, key=lambda x: x.player_id)
        )
        payload = f"{game_seed}|{team}|{version}|{signature}|roster-shots-v1"
        seed = int.from_bytes(hashlib.sha256(payload.encode()).digest()[:8], "big")
    rng = random.Random(int(seed))
    allocated = {r.player_id: [0] * len(team_shots) for r in roles}
    for path, total in enumerate(team_shots):
        for _ in range(total):
            allocated[_pick(rng, roles).player_id][path] += 1
    frozen = {player: tuple(values) for player, values in allocated.items()}
    return NHLRosterShotPaths(frozen, tuple(team_shots), int(seed), version)


def shots_over(paths: NHLRosterShotPaths, player_id: str, line: float) -> tuple[float, float, float]:
    if player_id not in paths.shots:
        raise ValueError("player not present in roster shot paths")
    if not math.isfinite(line):
        raise ValueError("line must be finite")
    values = [x - line for x in paths.shots[player_id]]
    n = len(values)
    wins = sum(x > 0 for x in values)
    pushes = sum(x == 0 for x in values)
    return wins / n, pushes / n, (n - wins - pushes) / n
