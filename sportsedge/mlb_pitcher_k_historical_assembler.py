"""Assemble one PIT-safe historical MLB pitcher-K evaluation row.

This adapter intentionally composes existing frozen/validated components. It does
not refit, price a new production model, or turn historical reconstruction into
forward evidence.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from .mlb_generic_features import MLBGenericHistorySource
from .mlb_pitcher_k_composite_candidate import build_composite_candidate
from .mlb_pitcher_k_historical_row import (
    acquire_historical_statcast_pitcher,
    bind_historical_statcast_skill,
    build_historical_evaluation_row,
)
from .mlb_pitcher_k_workload_candidate import build_workload_bundle


class PitcherKHistoricalAssemblerError(ValueError):
    pass


def _raw_prior_starts(source: MLBGenericHistorySource, *, pitcher_id: int, target_date: date) -> list[Mapping[str, Any]]:
    rows = source.player_rows(player_id=int(pitcher_id), group="pitching", target_date=target_date)
    starts = []
    for row in rows:
        stat = row.get("stat") if isinstance(row, Mapping) else None
        if not isinstance(stat, Mapping):
            continue
        try:
            if float(stat.get("gamesStarted", 0)) < 1:
                continue
        except (TypeError, ValueError):
            continue
        starts.append(row)
    return starts[-10:]


def assemble_historical_pitcher_k_row(
    *,
    source: MLBGenericHistorySource,
    season: int,
    target_date: date,
    game_id: int,
    pitcher_id: int,
    pitcher_team_id: int,
    away_team_id: int,
    home_team_id: int,
    realized_strikeouts: int,
    realized_batters_faced: int,
) -> dict[str, Any]:
    if int(season) != target_date.year or int(season) not in {2023, 2024, 2025}:
        raise PitcherKHistoricalAssemblerError("target outside frozen split")

    raw_starts = _raw_prior_starts(source, pitcher_id=pitcher_id, target_date=target_date)
    workload = build_workload_bundle(raw_starts)

    aligned = source._pitcher_start_rows_pk(player_id=int(pitcher_id), target_date=target_date)
    if len(aligned) != len(raw_starts):
        raise PitcherKHistoricalAssemblerError("workload/incumbent prior-start alignment mismatch")
    history_pool = [row for row, _, _, _ in aligned]

    opp_k, why = source._opp_k_payload(
        player_id=int(pitcher_id),
        target_date=target_date,
        team_id=int(pitcher_team_id),
        away_team_id=int(away_team_id),
        home_team_id=int(home_team_id),
    )
    if opp_k is None:
        raise PitcherKHistoricalAssemblerError(f"opponent-K context unavailable: {why}")

    lineup_k, _ = source._lineup_k_payload(
        game_pk=int(game_id),
        player_id=int(pitcher_id),
        target_date=target_date,
        opponent_id=int(opp_k["opponent_team_id"]),
    )
    composite = build_composite_candidate(
        workload=workload,
        opp_k_adjustment=opp_k,
        lineup_k_adjustment=lineup_k,
    )

    pitcher_context, provenance = acquire_historical_statcast_pitcher(
        entity_id=str(int(pitcher_id)),
        target_date=target_date,
        opener=source.opener,
    )
    skill_bound = bind_historical_statcast_skill(
        composite,
        pitcher_context=pitcher_context,
        provenance=provenance,
        target_date=target_date,
    )
    return build_historical_evaluation_row(
        season=int(season),
        target_date=target_date,
        game_id=int(game_id),
        pitcher_id=int(pitcher_id),
        candidate=skill_bound,
        history_pool=history_pool,
        realized_strikeouts=int(realized_strikeouts),
        realized_batters_faced=int(realized_batters_faced),
    )
