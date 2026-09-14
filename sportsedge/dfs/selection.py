from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable

from .contest import ContestEVResult, ContestStructure, evaluate_candidate_ev
from .field import FieldGenerationConfig, GeneratedField, generate_field, lineup_key
from .objective import DEFAULT_OBJECTIVE_WEIGHTS, ObjectiveWeights
from .optimizer import OptimizedLineup, optimize_single_entry
from .rules import SportRules
from .score_paths import AlignedScorePaths
from .types import DKPlayer, Projection


@dataclass(frozen=True)
class EVSelectionResult:
    lineup: OptimizedLineup
    ev: ContestEVResult
    field: GeneratedField
    candidates_generated: int
    candidates_evaluated: int
    candidate_evs: tuple[tuple[tuple[str, ...], float, float, str], ...]


def live_objective_variants(
    baseline: ObjectiveWeights = DEFAULT_OBJECTIVE_WEIGHTS,
) -> tuple[ObjectiveWeights, ...]:
    """Small preregistered live candidate neighborhood around the frozen baseline.

    This is not automatic parameter promotion. It simply produces several viable
    lineup constructions for contest-EV evaluation. Historical tuning controls
    which baseline/parameter set is allowed to become the next frozen version.
    """
    variants = [baseline]
    specs = (
        (0.24, 0.08, 0.05, 1.00),
        (0.44, 0.08, 0.05, 1.00),
        (0.34, 0.04, 0.05, 1.00),
        (0.34, 0.12, 0.05, 1.00),
        (0.34, 0.08, 0.02, 1.00),
        (0.34, 0.08, 0.08, 1.00),
        (0.34, 0.08, 0.05, 0.75),
        (0.34, 0.08, 0.05, 1.25),
    )
    for idx, (upside, low_own, chalk, corr) in enumerate(specs, 1):
        variants.append(
            replace(
                baseline,
                version=f"{baseline.version}_LIVEVAR_{idx}",
                upside_weight=upside,
                low_ownership_weight=low_own,
                chalk_penalty_weight=chalk,
                correlation_weight=corr,
            )
        )
    return tuple(variants)


def select_single_entry_by_ev(
    *,
    sport: str,
    rules: SportRules,
    players: list[DKPlayer],
    projections: dict[str, Projection],
    score_paths: AlignedScorePaths,
    contest: ContestStructure,
    field_config: FieldGenerationConfig,
    objective_variants: Iterable[ObjectiveWeights] | None = None,
    beam_width: int = 30_000,
    max_candidates: int = 8,
    max_simulations: int = 1500,
) -> EVSelectionResult:
    if contest.field_size != field_config.field_size + 1:
        raise ValueError(
            f"DFS_EV_FIELD_CONFIG_MISMATCH:{contest.field_size}:{field_config.field_size + 1}"
        )
    if max_candidates < 1 or max_candidates > 50:
        raise ValueError("DFS_EV_MAX_CANDIDATES_INVALID")
    field = generate_field(sport, rules, players, projections, field_config)

    variants = tuple(objective_variants or live_objective_variants())
    unique: dict[tuple[str, ...], OptimizedLineup] = {}
    for weights in variants:
        lineup = optimize_single_entry(
            sport,
            rules,
            players,
            projections,
            beam_width=beam_width,
            objective_weights=weights,
        )
        key = lineup_key(entry.player for entry in lineup.entries)
        if key not in unique:
            unique[key] = lineup
        if len(unique) >= max_candidates:
            break
    if not unique:
        raise ValueError("DFS_EV_CANDIDATES_EMPTY")

    evaluated: list[tuple[OptimizedLineup, ContestEVResult]] = []
    for lineup in unique.values():
        ev = evaluate_candidate_ev(
            candidate=(entry.player for entry in lineup.entries),
            field=field,
            contest=contest,
            score_paths=score_paths,
            max_simulations=max_simulations,
        )
        evaluated.append((lineup, ev))
    best_lineup, best_ev = max(
        evaluated,
        key=lambda row: (
            row[1].mean_profit,
            row[1].top_one_percent_rate,
            row[1].first_place_or_tied_rate,
            row[0].projected_points,
        ),
    )
    summary = tuple(
        sorted(
            (
                lineup_key(entry.player for entry in lineup.entries),
                ev.mean_profit,
                ev.roi,
                lineup.objective_version,
            )
            for lineup, ev in evaluated
        )
    )
    return EVSelectionResult(
        lineup=best_lineup,
        ev=best_ev,
        field=field,
        candidates_generated=len(unique),
        candidates_evaluated=len(evaluated),
        candidate_evs=summary,
    )
