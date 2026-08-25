"""Deterministic football situational read-outs over shared Engine A paths.

These functions never create a second simulation. They consume the ordered
scoring-event path and expose structural probabilities for situational markets.
Markets whose production specification also depends on Engine C remain
unpromoted until special-teams/event typing is implemented and validated.
"""

from __future__ import annotations

from collections.abc import Iterable

from .football_path import FootballGamePath, ScoringEvent


def _require_paths(paths: Iterable[FootballGamePath]) -> list[FootballGamePath]:
    materialized = list(paths)
    if not materialized:
        raise ValueError("SIMULATION_PATHS_EMPTY")
    if any(not isinstance(path, FootballGamePath) for path in materialized):
        raise ValueError("FOOTBALL_GAME_PATH_REQUIRED")
    return materialized


def _require_point_threshold(n: int) -> int:
    if isinstance(n, bool) or not isinstance(n, int) or n <= 0:
        raise ValueError("POINT_THRESHOLD_MUST_BE_POSITIVE_INTEGER")
    return int(n)


def _window_events(path: FootballGamePath, *, include_ot: bool) -> tuple[ScoringEvent, ...]:
    if not isinstance(include_ot, bool):
        raise ValueError("OT_RULE_MUST_BE_BOOLEAN")
    if include_ot:
        return path.events
    return tuple(event for event in path.events if event.period <= 4)


def _score_timeline(
    path: FootballGamePath,
    *,
    include_ot: bool,
) -> list[tuple[int, int]]:
    home = 0
    away = 0
    timeline = [(0, 0)]
    for event in _window_events(path, include_ot=include_ot):
        if event.team == path.home_team:
            home += event.points
        elif event.team == path.away_team:
            away += event.points
        else:  # FootballGamePath already rejects this; retain fail-closed locality.
            raise ValueError("SCORING_EVENT_TEAM_MISMATCH")
        timeline.append((home, away))
    return timeline


def derive_race_to_n(
    paths: Iterable[FootballGamePath],
    *,
    n: int,
    include_ot: bool,
) -> dict[str, float]:
    """Return raw first-to-N probabilities including the unresolved-neither state.

    ``neither`` is intentionally not converted to a win/loss/void outcome here;
    that is sportsbook-rule settlement policy and must be supplied downstream.
    """

    threshold = _require_point_threshold(n)
    materialized = _require_paths(paths)
    counts = {"home_first": 0, "away_first": 0, "neither": 0}

    for path in materialized:
        home = 0
        away = 0
        winner: str | None = None
        for event in _window_events(path, include_ot=include_ot):
            if event.team == path.home_team:
                home += event.points
                if home >= threshold:
                    winner = "home_first"
                    break
            elif event.team == path.away_team:
                away += event.points
                if away >= threshold:
                    winner = "away_first"
                    break
            else:
                raise ValueError("SCORING_EVENT_TEAM_MISMATCH")
        counts[winner or "neither"] += 1

    denominator = float(len(materialized))
    return {key: value / denominator for key, value in counts.items()}


def _largest_lead(path: FootballGamePath, *, side: str, include_ot: bool) -> int:
    normalized = str(side).strip().lower()
    if normalized not in {"home", "away"}:
        raise ValueError(f"UNSUPPORTED_TEAM_SIDE:{side}")
    timeline = _score_timeline(path, include_ot=include_ot)
    if normalized == "home":
        return max(home - away for home, away in timeline)
    return max(away - home for home, away in timeline)


def derive_largest_lead(
    paths: Iterable[FootballGamePath],
    *,
    side: str,
    line: float,
    include_ot: bool,
) -> dict[str, float]:
    """Price a largest-lead O/U line from intermediate score states."""

    materialized = _require_paths(paths)
    normalized = str(side).strip().lower()
    if normalized not in {"home", "away"}:
        raise ValueError(f"UNSUPPORTED_TEAM_SIDE:{side}")
    lead_line = float(line)
    if lead_line < 0:
        raise ValueError("LEAD_LINE_MUST_BE_NONNEGATIVE")

    leads = [_largest_lead(path, side=normalized, include_ot=include_ot) for path in materialized]
    denominator = float(len(leads))
    return {
        "over": sum(value > lead_line for value in leads) / denominator,
        "under": sum(value < lead_line for value in leads) / denominator,
        "push": sum(value == lead_line for value in leads) / denominator,
    }


def _final_margin(path: FootballGamePath, *, include_ot: bool) -> int:
    timeline = _score_timeline(path, include_ot=include_ot)
    home, away = timeline[-1]
    return home - away


def derive_winning_margin_band(
    paths: Iterable[FootballGamePath],
    *,
    lower: float,
    upper: float,
    include_ot: bool,
    lower_inclusive: bool = True,
    upper_inclusive: bool = True,
) -> dict[str, float]:
    """Price a signed home-margin band without inventing team/band semantics.

    Positive values are home winning margins, negative values are away winning
    margins, and zero is a tie. Team-specific sportsbook bands should be mapped
    to these signed bounds before this read-out is called.
    """

    materialized = _require_paths(paths)
    lo = float(lower)
    hi = float(upper)
    if lo > hi:
        raise ValueError("MARGIN_BAND_BOUNDS_INVALID")
    if not isinstance(lower_inclusive, bool) or not isinstance(upper_inclusive, bool):
        raise ValueError("MARGIN_BAND_ENDPOINT_RULE_MUST_BE_BOOLEAN")

    def inside(value: float) -> bool:
        low_ok = value >= lo if lower_inclusive else value > lo
        high_ok = value <= hi if upper_inclusive else value < hi
        return low_ok and high_ok

    hits = sum(inside(_final_margin(path, include_ot=include_ot)) for path in materialized)
    probability = hits / float(len(materialized))
    return {"in_band": probability, "out_of_band": 1.0 - probability}


def derive_both_teams_to_n(
    paths: Iterable[FootballGamePath],
    *,
    n: int,
    include_ot: bool,
) -> dict[str, float]:
    """Price the Boolean event that both teams reach at least N points."""

    threshold = _require_point_threshold(n)
    materialized = _require_paths(paths)
    yes = 0
    for path in materialized:
        home, away = _score_timeline(path, include_ot=include_ot)[-1]
        yes += home >= threshold and away >= threshold
    probability = yes / float(len(materialized))
    return {"yes": probability, "no": 1.0 - probability}
