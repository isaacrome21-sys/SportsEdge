from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from .rules import SportRules
from .types import DKPlayer, Projection


@dataclass(frozen=True)
class LineupEntry:
    slot: str
    player: DKPlayer
    projection: Projection


@dataclass(frozen=True)
class OptimizedLineup:
    entries: tuple[LineupEntry, ...]
    salary: int
    projected_points: float
    ceiling: float
    objective: float
    correlation_score: float


@dataclass(frozen=True)
class _State:
    chosen: tuple[tuple[int, str], ...]
    used: frozenset[str]
    salary: int
    base_score: float
    projected_points: float
    ceiling: float
    team_counts: tuple[tuple[str, int], ...]


def _base_player_score(proj: Projection) -> float:
    score = proj.mean + 0.34 * proj.upside
    if proj.ownership is not None:
        own = max(0.0, min(1.0, proj.ownership))
        # Single-entry GPP: reward useful ceiling at lower ownership without making ownership the projection.
        score += 0.08 * proj.mean * max(0.0, 0.20 - own)
        score -= 0.05 * proj.mean * max(0.0, own - 0.28)
    return score


def _is_pitcher(p: DKPlayer) -> bool:
    return p.is_pitcher


def _is_dst(p: DKPlayer) -> bool:
    return p.is_defense


def _mlb_conflict(chosen: Iterable[DKPlayer], candidate: DKPlayer) -> bool:
    for p in chosen:
        if _is_pitcher(p) and not _is_pitcher(candidate):
            if candidate.team and p.opponent and candidate.team == p.opponent:
                return True
        if _is_pitcher(candidate) and not _is_pitcher(p):
            if p.team and candidate.opponent and p.team == candidate.opponent:
                return True
    return False


def _football_dst_conflict(chosen: Iterable[DKPlayer], candidate: DKPlayer) -> bool:
    if not _is_dst(candidate):
        if any(_is_dst(p) and p.opponent == candidate.team for p in chosen):
            return True
        return False
    return any(not _is_dst(p) and candidate.opponent == p.team for p in chosen)


def _incremental_correlation(sport: str, chosen: Iterable[DKPlayer], candidate: DKPlayer) -> float:
    chosen = tuple(chosen)
    if sport == "MLB":
        if _is_pitcher(candidate):
            return 0.0
        same = sum(1 for p in chosen if not _is_pitcher(p) and p.team == candidate.team)
        return 0.22 * same * same
    bonus = 0.0
    cpos = set(candidate.positions)
    for p in chosen:
        ppos = set(p.positions)
        same_team = candidate.team and candidate.team == p.team
        same_game_opp = candidate.team and p.team and candidate.team == p.opponent
        if same_team and (("QB" in cpos and bool(ppos & {"WR", "TE"})) or ("QB" in ppos and bool(cpos & {"WR", "TE"}))):
            bonus += 1.20 if sport == "NFL" else 1.00
        if same_game_opp and ("QB" in cpos or "QB" in ppos):
            bonus += 0.28
        if sport == "NFL" and same_team and ((_is_dst(candidate) and "RB" in ppos) or (_is_dst(p) and "RB" in cpos)):
            bonus += 0.18
    return bonus


def _final_correlation(sport: str, players: tuple[DKPlayer, ...]) -> float:
    if sport == "MLB":
        counts = Counter(p.team for p in players if not _is_pitcher(p) and p.team)
        sizes = sorted(counts.values(), reverse=True)
        score = 0.0
        if sizes:
            score += {1: 0.0, 2: 0.5, 3: 1.4, 4: 2.7, 5: 4.2}.get(sizes[0], 4.2)
        if len(sizes) > 1:
            score += {1: 0.0, 2: 0.45, 3: 0.95, 4: 1.2}.get(sizes[1], 1.2)
        return score
    score = 0.0
    for qb in (p for p in players if "QB" in p.positions):
        same_pass = sum(1 for p in players if p.player_id != qb.player_id and p.team == qb.team and bool(set(p.positions) & {"WR", "TE"}))
        bring_back = sum(1 for p in players if p.team == qb.opponent and bool(set(p.positions) & {"RB", "WR", "TE"}))
        if same_pass >= 1:
            score += 1.5
        if same_pass >= 2:
            score += 0.5
        if bring_back >= 1:
            score += 0.4
    return score


def _valid_final(sport: str, rules: SportRules, players: tuple[DKPlayer, ...]) -> bool:
    if len({p.team for p in players if p.team}) < rules.min_teams:
        return False
    if sport == "MLB":
        hitters = Counter(p.team for p in players if not _is_pitcher(p) and p.team)
        if rules.max_hitters_per_team and any(v > rules.max_hitters_per_team for v in hitters.values()):
            return False
    if sport in {"NFL", "CFB"}:
        for qb in (p for p in players if "QB" in p.positions):
            # Tournament construction rule: each rostered QB should have at least one same-team WR/TE.
            if not any(
                x.player_id != qb.player_id
                and x.team == qb.team
                and bool(set(x.positions) & {"WR", "TE"})
                for x in players
            ):
                return False
    return True


def optimize_single_entry(
    sport: str,
    rules: SportRules,
    players: list[DKPlayer],
    projections: dict[str, Projection],
    *,
    beam_width: int = 30_000,
    per_slot_limit: int = 70,
) -> OptimizedLineup:
    sport = sport.upper()
    pool = [p for p in players if not p.is_disabled and p.player_id in projections and p.salary > 0]
    if not pool:
        raise ValueError("DFS_PLAYER_POOL_EMPTY")
    pool_index = {p.player_id: idx for idx, p in enumerate(pool)}

    canonical_slots = list(rules.slots)
    slot_candidates: dict[int, list[DKPlayer]] = {}
    for idx, slot in enumerate(canonical_slots):
        eligible = [p for p in pool if p.eligible_for(slot)]
        if not eligible:
            raise ValueError(f"DFS_NO_ELIGIBLE_PLAYERS:{slot}")
        eligible.sort(key=lambda p: (_base_player_score(projections[p.player_id]), projections[p.player_id].mean), reverse=True)
        slot_candidates[idx] = eligible[:per_slot_limit]

    # Fill restrictive slots first while preserving original slot identity.
    slot_order = sorted(range(len(canonical_slots)), key=lambda i: (len(slot_candidates[i]), canonical_slots[i]))
    states = [_State((), frozenset(), 0, 0.0, 0.0, 0.0, ())]
    min_salary_by_remaining = []
    for pos, slot_idx in enumerate(slot_order):
        remaining = slot_order[pos + 1 :]
        min_salary_by_remaining.append(sum(min(p.salary for p in slot_candidates[r]) for r in remaining))

    for step, slot_idx in enumerate(slot_order):
        slot = canonical_slots[slot_idx]
        expanded: list[_State] = []
        min_remaining = min_salary_by_remaining[step]
        for state in states:
            chosen_players = tuple(pool[pidx] for pidx, _ in state.chosen)
            team_counts = dict(state.team_counts)
            for cand in slot_candidates[slot_idx]:
                if cand.player_id in state.used:
                    continue
                salary = state.salary + cand.salary
                if salary + min_remaining > rules.salary_cap:
                    continue
                if sport == "MLB" and _mlb_conflict(chosen_players, cand):
                    continue
                if sport == "NFL" and _football_dst_conflict(chosen_players, cand):
                    continue
                if sport == "MLB" and not _is_pitcher(cand) and rules.max_hitters_per_team:
                    if team_counts.get(cand.team, 0) >= rules.max_hitters_per_team:
                        continue
                proj = projections[cand.player_id]
                inc_corr = _incremental_correlation(sport, chosen_players, cand)
                new_counts = dict(team_counts)
                if sport == "MLB" and not _is_pitcher(cand):
                    new_counts[cand.team] = new_counts.get(cand.team, 0) + 1
                pidx = pool_index[cand.player_id]
                expanded.append(
                    _State(
                        chosen=state.chosen + ((pidx, slot),),
                        used=state.used | {cand.player_id},
                        salary=salary,
                        base_score=state.base_score + _base_player_score(proj) + inc_corr,
                        projected_points=state.projected_points + proj.mean,
                        ceiling=state.ceiling + proj.ceiling,
                        team_counts=tuple(sorted(new_counts.items())),
                    )
                )
        if not expanded:
            raise ValueError(f"DFS_OPTIMIZER_EXHAUSTED_AT:{slot}")
        expanded.sort(key=lambda s: (s.base_score, s.projected_points, s.salary), reverse=True)
        states = expanded[:beam_width]

    best: OptimizedLineup | None = None
    for state in states:
        selected = tuple(pool[pidx] for pidx, _ in state.chosen)
        if not _valid_final(sport, rules, selected):
            continue
        final_corr = _final_correlation(sport, selected)
        objective = state.base_score + final_corr
        entries_unsorted = [
            LineupEntry(slot=slot, player=pool[pidx], projection=projections[pool[pidx].player_id])
            for pidx, slot in state.chosen
        ]
        # Reconstruct in canonical slot order, preserving duplicate slot names by taking in insertion order.
        entries: list[LineupEntry] = []
        remaining = entries_unsorted[:]
        for slot in canonical_slots:
            for i, entry in enumerate(remaining):
                if entry.slot == slot:
                    entries.append(entry)
                    remaining.pop(i)
                    break
        lineup = OptimizedLineup(
            entries=tuple(entries),
            salary=state.salary,
            projected_points=state.projected_points,
            ceiling=state.ceiling,
            objective=objective,
            correlation_score=final_corr,
        )
        if best is None or lineup.objective > best.objective:
            best = lineup
    if best is None:
        raise ValueError("DFS_NO_VALID_LINEUP")
    return best
