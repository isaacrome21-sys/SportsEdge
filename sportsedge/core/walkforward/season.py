"""Strict season-based walk-forward splitting for football validation."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterable, Mapping
from typing import Any


@dataclass(frozen=True)
class SeasonFold:
    train_seasons: tuple[int, ...]
    test_season: int
    train_rows: tuple[Mapping[str, Any], ...]
    test_rows: tuple[Mapping[str, Any], ...]


def season_walk_forward(
    rows: Iterable[Mapping[str, Any]],
    *,
    season_key: str = "season",
    min_train_seasons: int = 1,
) -> list[SeasonFold]:
    """Create expanding season folds with no shuffle and no future leakage."""

    if min_train_seasons < 1:
        raise ValueError("min_train_seasons must be >= 1")
    materialized = list(rows)
    if not materialized:
        return []
    if any(season_key not in row for row in materialized):
        raise ValueError("SEASON_KEY_MISSING")

    try:
        seasons = sorted({int(row[season_key]) for row in materialized})
    except (TypeError, ValueError) as exc:
        raise ValueError("SEASON_INVALID") from exc

    folds: list[SeasonFold] = []
    for index in range(min_train_seasons, len(seasons)):
        test_season = seasons[index]
        train_seasons = tuple(seasons[:index])
        train_rows = tuple(row for row in materialized if int(row[season_key]) in train_seasons)
        test_rows = tuple(row for row in materialized if int(row[season_key]) == test_season)
        if any(int(row[season_key]) >= test_season for row in train_rows):
            raise AssertionError("WALK_FORWARD_LEAKAGE")
        if any(int(row[season_key]) != test_season for row in test_rows):
            raise AssertionError("WALK_FORWARD_TEST_CONTAMINATION")
        folds.append(
            SeasonFold(
                train_seasons=train_seasons,
                test_season=test_season,
                train_rows=train_rows,
                test_rows=test_rows,
            )
        )
    return folds
