from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
import random
from typing import Iterable

from .optimizer import _football_dst_conflict, _mlb_conflict, _valid_final
from .rules import SportRules
from .types import DKPlayer, Projection


@dataclass(frozen=True)
class FieldGenerationConfig:
    field_size: int
    seed: int
    min_salary: int = 47_000
    ownership_exponent: float = 1.0
    stack_strength: float = 1.0
    bringback_strength: float = 0.30
    max_attempt_multiplier: int = 80
    version: str = "DFS_FIELD_GEN_V1"

    def validate(self) -> None:
        if self.field_size < 2:
            raise ValueError("DFS_FIELD_SIZE_TOO_SMALL")
        if self.seed < 0:
            raise ValueError("DFS_FIELD_SEED_INVALID")
        if self.min_salary < 0:
            raise ValueError("DFS_FIELD_MIN_SALARY_INVALID")
        if not 0.1 <= self.ownership_exponent <= 4.0:
            raise ValueError("DFS_FIELD_OWNERSHIP_EXPONENT_INVALID")
        if not 0.0 <= self.stack_strength <= 10.0:
            raise ValueError("DFS_FIELD_STACK_STRENGTH_INVALID")
        if not 0.0 <= self.bringback_strength <= 10.0:
            raise ValueError("DFS_FIELD_BRINGBACK_STRENGTH_INVALID")
        if self.max_attempt_multiplier < 2:
            raise ValueError("DFS_FIELD_ATTEMPT_MULTIPLIER_INVALID")


@dataclass(frozen=True)
class GeneratedField:
    counts: dict[tuple[str, ...], int]
    salaries: dict[tuple[str, ...], int]
    field_size: int
    unique_lineups: int
    duplicate_entries: int
    attempts: int
    config: FieldGenerationConfig
    ownership_coverage: float

    @property
    def duplicate_rate(self) -> float:
        return self.duplicate_entries / max(1, self.field_size)


def lineup_key(players: Iterable[DKPlayer] | Iterable[str]) -> tuple[str, ...]:
    ids: list[str] = []
    for value in players:
        if isinstance(value, DKPlayer):
            ids.append(value.player_id)
        else:
            ids.append(str(value))
    if len(ids) != len(set(ids)):
        raise ValueError("DFS_LINEUP_DUPLICATE_PLAYER")
    return tuple(sorted(ids))


def _ownership(proj: Projection) -> float:
    if proj.ownership is None:
        raise ValueError(f"DFS_OWNERSHIP_MISSING:{proj.player_id}")
    own = float(proj.ownership)
    if not 0.0 <= own <= 1.0:
        raise ValueError(f"DFS_OWNERSHIP_OUT_OF_RANGE:{proj.player_id}:{own}")
    return own


def _correlation_multiplier(
    sport: str,
    chosen: tuple[DKPlayer, ...],
    candidate: DKPlayer,
    config: FieldGenerationConfig,
) -> float:
    if not chosen:
        return 1.0
    sport = sport.upper()
    multiplier = 1.0
    if sport == "MLB" and not candidate.is_pitcher:
        same_hitters = sum(1 for p in chosen if not p.is_pitcher and p.team == candidate.team)
        if same_hitters:
            multiplier *= 1.0 + config.stack_strength * (same_hitters ** 1.25)
        return multiplier

    cpos = set(candidate.positions)
    for player in chosen:
        ppos = set(player.positions)
        if candidate.team == player.team:
            qb_passcatcher = (
                ("QB" in cpos and bool(ppos & {"WR", "TE"}))
                or ("QB" in ppos and bool(cpos & {"WR", "TE"}))
            )
            if qb_passcatcher:
                multiplier *= 1.0 + config.stack_strength
        if candidate.team == player.opponent and ("QB" in cpos or "QB" in ppos):
            if bool(cpos & {"RB", "WR", "TE", "QB"}) and bool(ppos & {"RB", "WR", "TE", "QB"}):
                multiplier *= 1.0 + config.bringback_strength
    return multiplier


def _weighted_pick(
    rng: random.Random,
    candidates: list[DKPlayer],
    projections: dict[str, Projection],
    sport: str,
    chosen: tuple[DKPlayer, ...],
    config: FieldGenerationConfig,
) -> DKPlayer:
    weights: list[float] = []
    for player in candidates:
        own = _ownership(projections[player.player_id])
        base = max(1e-6, own) ** config.ownership_exponent
        weights.append(base * _correlation_multiplier(sport, chosen, player, config))
    total = sum(weights)
    if not math.isfinite(total) or total <= 0:
        raise ValueError("DFS_FIELD_WEIGHTS_INVALID")
    return rng.choices(candidates, weights=weights, k=1)[0]


def _try_lineup(
    *,
    rng: random.Random,
    sport: str,
    rules: SportRules,
    pool: list[DKPlayer],
    projections: dict[str, Projection],
    config: FieldGenerationConfig,
) -> tuple[DKPlayer, ...] | None:
    slot_candidates: dict[int, list[DKPlayer]] = {}
    for idx, slot in enumerate(rules.slots):
        eligible = [p for p in pool if p.eligible_for(slot)]
        if not eligible:
            raise ValueError(f"DFS_FIELD_NO_ELIGIBLE_PLAYERS:{slot}")
        slot_candidates[idx] = eligible
    order = sorted(range(len(rules.slots)), key=lambda idx: (len(slot_candidates[idx]), rules.slots[idx]))
    chosen: list[DKPlayer] = []
    used: set[str] = set()
    salary = 0
    hitter_counts: Counter[str] = Counter()

    for step, slot_idx in enumerate(order):
        slot = rules.slots[slot_idx]
        remaining_slots = order[step + 1 :]
        candidates: list[DKPlayer] = []
        for player in slot_candidates[slot_idx]:
            if player.player_id in used:
                continue
            if salary + player.salary > rules.salary_cap:
                continue
            if sport == "MLB" and _mlb_conflict(chosen, player):
                continue
            if sport == "NFL" and _football_dst_conflict(chosen, player):
                continue
            if sport == "MLB" and not player.is_pitcher and rules.max_hitters_per_team:
                if hitter_counts[player.team] >= rules.max_hitters_per_team:
                    continue
            min_remaining = 0
            feasible = True
            blocked_ids = used | {player.player_id}
            for rem_idx in remaining_slots:
                rem = [
                    p.salary for p in slot_candidates[rem_idx]
                    if p.player_id not in blocked_ids
                ]
                if not rem:
                    feasible = False
                    break
                min_remaining += min(rem)
            if not feasible or salary + player.salary + min_remaining > rules.salary_cap:
                continue
            candidates.append(player)
        if not candidates:
            return None
        pick = _weighted_pick(rng, candidates, projections, sport, tuple(chosen), config)
        chosen.append(pick)
        used.add(pick.player_id)
        salary += pick.salary
        if sport == "MLB" and not pick.is_pitcher:
            hitter_counts[pick.team] += 1

    selected = tuple(chosen)
    if salary < config.min_salary or salary > rules.salary_cap:
        return None
    if not _valid_final(sport, rules, selected):
        return None
    return selected


def generate_field(
    sport: str,
    rules: SportRules,
    players: list[DKPlayer],
    projections: dict[str, Projection],
    config: FieldGenerationConfig,
) -> GeneratedField:
    """Generate a contest field from calibrated ownership plus sport correlations.

    This is a field-behavior model, not a player projection model. Its parameters
    must be calibrated on historical contest ownership/lineup data before a live
    field simulation is described as validated.
    """
    config.validate()
    sport = sport.upper()
    active = [p for p in players if not p.is_disabled and p.salary > 0 and p.player_id in projections]
    with_ownership = []
    for player in active:
        proj = projections[player.player_id]
        if proj.ownership is None:
            continue
        _ownership(proj)
        with_ownership.append(player)
    coverage = len(with_ownership) / max(1, len(active))
    if coverage < 0.90:
        raise ValueError(f"DFS_FIELD_OWNERSHIP_COVERAGE_TOO_LOW:{coverage:.3f}")

    rng = random.Random(config.seed)
    counts: Counter[tuple[str, ...]] = Counter()
    salaries: dict[tuple[str, ...], int] = {}
    attempts = 0
    max_attempts = config.field_size * config.max_attempt_multiplier
    while sum(counts.values()) < config.field_size and attempts < max_attempts:
        attempts += 1
        selected = _try_lineup(
            rng=rng,
            sport=sport,
            rules=rules,
            pool=with_ownership,
            projections=projections,
            config=config,
        )
        if selected is None:
            continue
        key = lineup_key(selected)
        counts[key] += 1
        salaries.setdefault(key, sum(p.salary for p in selected))
    generated = sum(counts.values())
    if generated != config.field_size:
        raise ValueError(f"DFS_FIELD_GENERATION_INCOMPLETE:{generated}:{config.field_size}:{attempts}")
    unique = len(counts)
    return GeneratedField(
        counts=dict(counts),
        salaries=salaries,
        field_size=generated,
        unique_lineups=unique,
        duplicate_entries=generated - unique,
        attempts=attempts,
        config=config,
        ownership_coverage=coverage,
    )
