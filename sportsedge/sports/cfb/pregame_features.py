"""Pregame CFB feature policy with a strict Week-1 prior-season fallback.

Week 2+ snapshots use only the target season and delegate to the existing strict
week-to-date builder. Week 1 may use only completed games from the immediately
preceding season. Target-season Week-1/future rows are structurally excluded from
that fallback. Missing prior-season completed data fails closed.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Iterable, Mapping

from .historical_features import build_week_to_date_metrics


class CFBPregameFeatureError(ValueError):
    pass


@dataclass(frozen=True)
class HistoryWindow:
    schedules: tuple[dict[str, Any], ...]
    source_season: int
    delegate_through_week: int
    sample_source: str


def _int(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise CFBPregameFeatureError(f"{name}:integer required")
    try:
        return int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise CFBPregameFeatureError(f"{name}:integer required") from exc


def _completed(row: Mapping[str, Any]) -> bool:
    raw = row.get("status_type_completed", row.get("completed"))
    if type(raw) is bool:
        return raw
    text = str(raw or "").strip().lower()
    if text in {"true", "t", "1"}:
        return True
    if text in {"false", "f", "0"}:
        return False
    raise CFBPregameFeatureError("schedule.completed:bool required")


def select_history_window(
    schedules: Iterable[Mapping[str, Any]], *, season: int, through_week: int
) -> HistoryWindow:
    year = _int(season, "season")
    week = _int(through_week, "through_week")
    if week <= 0:
        raise CFBPregameFeatureError("through_week must be positive")

    rows: list[dict[str, Any]] = []
    for raw in schedules:
        if not isinstance(raw, Mapping):
            raise CFBPregameFeatureError("schedules:row object required")
        rows.append(dict(raw))

    if week > 1:
        current = tuple(
            row for row in rows
            if _int(row.get("season"), "schedule.season") == year
        )
        return HistoryWindow(
            schedules=current,
            source_season=year,
            delegate_through_week=week,
            sample_source="SPORTSDATAVERSE_WEEK_TO_DATE_V1",
        )

    prior_year = year - 1
    prior: list[dict[str, Any]] = []
    max_week = 0
    for row in rows:
        if _int(row.get("season"), "schedule.season") != prior_year:
            continue
        if not _completed(row):
            continue
        row_week = _int(row.get("week"), "schedule.week")
        max_week = max(max_week, row_week)
        remapped = dict(row)
        # The underlying builder intentionally accepts one season at a time. The
        # immutable game ids remain unchanged; only the copied schedule's season
        # selector is rebound to the target season for feature construction.
        remapped["season"] = year
        prior.append(remapped)

    if not prior:
        raise CFBPregameFeatureError("CFB_HISTORICAL_PRIOR_SEASON_REQUIRED")

    return HistoryWindow(
        schedules=tuple(prior),
        source_season=prior_year,
        delegate_through_week=max_week + 1,
        sample_source="SPORTSDATAVERSE_PRIOR_SEASON_FALLBACK_V1",
    )


def build_pregame_metrics(
    *,
    season: int,
    through_week: int,
    schedules: Iterable[Mapping[str, Any]],
    adv_team: Iterable[Mapping[str, Any]],
    adv_situational: Iterable[Mapping[str, Any]],
    adv_drives: Iterable[Mapping[str, Any]],
    play_by_play: Iterable[Mapping[str, Any]],
    feature_asof_ts: str,
):
    year = _int(season, "season")
    week = _int(through_week, "through_week")
    window = select_history_window(schedules, season=year, through_week=week)
    out = build_week_to_date_metrics(
        season=year,
        through_week=window.delegate_through_week,
        schedules=window.schedules,
        adv_team=tuple(adv_team),
        adv_situational=tuple(adv_situational),
        adv_drives=tuple(adv_drives),
        play_by_play=tuple(play_by_play),
        feature_asof_ts=feature_asof_ts,
    )
    if week > 1:
        return out
    return {
        name: replace(metric, through_week=0, sample_source=window.sample_source)
        for name, metric in out.items()
    }
