from __future__ import annotations

"""Coherent NHL player block/hit distributions.

Team event counts are simulated once per game path from explicit versioned
expectations, then each event is allocated exactly once across an active roster
using PIT-safe role weights.  This mirrors SportsEdge's shared SOG allocation:
player props share one team environment rather than independent player draws.
"""

from dataclasses import dataclass
import hashlib
import math
import random
from typing import Sequence


@dataclass(frozen=True)
class NHLTeamPeripheralParameters:
    version: str
    expected_blocks: float
    expected_hits: float
    source: str
    history_sha256: str

    def validate(self) -> None:
        if not all((self.version, self.source, self.history_sha256)):
            raise ValueError("peripheral parameter provenance required")
        for name, value in (("expected_blocks", self.expected_blocks), ("expected_hits", self.expected_hits)):
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and nonnegative")


@dataclass(frozen=True)
class NHLTeamPeripheralPaths:
    blocks: tuple[int, ...]
    hits: tuple[int, ...]
    seed: int
    parameter_version: str

    @property
    def simulations(self) -> int:
        return len(self.blocks)


@dataclass(frozen=True)
class NHLPeripheralRole:
    player_id: str
    team: str
    captured_at: str
    source: str
    version: str
    block_weight: float
    hit_weight: float
    lineup_status: str

    def validate(self) -> None:
        if not all((self.player_id, self.captured_at, self.source, self.version)):
            raise ValueError("peripheral role identity/provenance required")
        if self.team not in {"HOME", "AWAY"}:
            raise ValueError("team must be HOME or AWAY")
        if self.lineup_status not in {"CONFIRMED", "PROJECTED"}:
            raise ValueError("invalid lineup status")
        for name, value in (("block_weight", self.block_weight), ("hit_weight", self.hit_weight)):
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and nonnegative")


@dataclass(frozen=True)
class NHLRosterPeripheralPaths:
    blocks: dict[str, tuple[int, ...]]
    hits: dict[str, tuple[int, ...]]
    team_blocks: tuple[int, ...]
    team_hits: tuple[int, ...]
    seed: int
    version: str


def _poisson(rng: random.Random, lam: float) -> int:
    if lam == 0:
        return 0
    limit = math.exp(-lam)
    product = 1.0
    count = 0
    while product > limit:
        count += 1
        product *= rng.random()
    return count - 1


def simulate_team_peripheral_paths(
    game_id: str,
    params: NHLTeamPeripheralParameters,
    *,
    simulations: int = 20_000,
    seed: int | None = None,
) -> NHLTeamPeripheralPaths:
    params.validate()
    if not game_id or simulations <= 0:
        raise ValueError("game_id and positive simulations required")
    if seed is None:
        payload = (
            f"{game_id}|{params.version}|{params.expected_blocks:.12g}|"
            f"{params.expected_hits:.12g}|team-peripherals-v1"
        )
        seed = int.from_bytes(hashlib.sha256(payload.encode()).digest()[:8], "big")
    rng = random.Random(int(seed))
    blocks = tuple(_poisson(rng, params.expected_blocks) for _ in range(simulations))
    hits = tuple(_poisson(rng, params.expected_hits) for _ in range(simulations))
    return NHLTeamPeripheralPaths(blocks, hits, int(seed), params.version)


def _pick(rng: random.Random, roles: Sequence[NHLPeripheralRole], stat: str) -> NHLPeripheralRole:
    if stat not in {"blocks", "hits"}:
        raise ValueError("stat must be blocks or hits")
    weights = [r.block_weight if stat == "blocks" else r.hit_weight for r in roles]
    total = sum(weights)
    if total <= 0:
        raise ValueError(f"positive roster {stat} weight required")
    target = rng.random() * total
    acc = 0.0
    for role, weight in zip(roles, weights):
        acc += weight
        if target <= acc:
            return role
    return roles[-1]


def simulate_roster_peripheral_paths(
    team_paths: NHLTeamPeripheralPaths,
    roles: Sequence[NHLPeripheralRole],
    *,
    team: str,
    version: str,
    game_seed: int,
    seed: int | None = None,
) -> NHLRosterPeripheralPaths:
    roles = tuple(roles)
    if not roles or not version:
        raise ValueError("roster and version required")
    if len(team_paths.blocks) != len(team_paths.hits) or not team_paths.blocks:
        raise ValueError("aligned nonempty team peripheral paths required")
    if any(r.team != team for r in roles):
        raise ValueError("mixed-team peripheral roster")
    if len({r.player_id for r in roles}) != len(roles):
        raise ValueError("duplicate player")
    for role in roles:
        role.validate()
    if sum(r.block_weight for r in roles) <= 0 or sum(r.hit_weight for r in roles) <= 0:
        raise ValueError("positive roster block and hit weights required")
    if seed is None:
        signature = "|".join(
            f"{r.player_id}:{r.version}:{r.block_weight:.12g}:{r.hit_weight:.12g}"
            for r in sorted(roles, key=lambda x: x.player_id)
        )
        payload = f"{int(game_seed)}|{team}|{version}|{signature}|roster-peripherals-v1"
        seed = int.from_bytes(hashlib.sha256(payload.encode()).digest()[:8], "big")
    rng = random.Random(int(seed))
    blocks = {r.player_id: [0] * len(team_paths.blocks) for r in roles}
    hits = {r.player_id: [0] * len(team_paths.hits) for r in roles}
    for path, total in enumerate(team_paths.blocks):
        if total < 0:
            raise ValueError("team blocks must be nonnegative")
        for _ in range(total):
            blocks[_pick(rng, roles, "blocks").player_id][path] += 1
    for path, total in enumerate(team_paths.hits):
        if total < 0:
            raise ValueError("team hits must be nonnegative")
        for _ in range(total):
            hits[_pick(rng, roles, "hits").player_id][path] += 1
    return NHLRosterPeripheralPaths(
        blocks={p: tuple(v) for p, v in blocks.items()},
        hits={p: tuple(v) for p, v in hits.items()},
        team_blocks=team_paths.blocks,
        team_hits=team_paths.hits,
        seed=int(seed),
        version=version,
    )


def peripheral_over(
    paths: NHLRosterPeripheralPaths,
    *,
    player_id: str,
    stat: str,
    line: float,
) -> tuple[float, float, float]:
    if stat == "blocks":
        mapping = paths.blocks
    elif stat == "hits":
        mapping = paths.hits
    else:
        raise ValueError("stat must be blocks or hits")
    if player_id not in mapping:
        raise ValueError("player not present in peripheral paths")
    if not math.isfinite(line):
        raise ValueError("line must be finite")
    diffs = [value - line for value in mapping[player_id]]
    n = len(diffs)
    wins = sum(x > 0 for x in diffs)
    pushes = sum(x == 0 for x in diffs)
    return wins / n, pushes / n, (n - wins - pushes) / n


__all__ = [
    "NHLTeamPeripheralParameters",
    "NHLTeamPeripheralPaths",
    "NHLPeripheralRole",
    "NHLRosterPeripheralPaths",
    "simulate_team_peripheral_paths",
    "simulate_roster_peripheral_paths",
    "peripheral_over",
]
