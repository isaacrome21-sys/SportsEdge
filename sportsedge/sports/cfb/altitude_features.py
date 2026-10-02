"""Fail-closed feature construction for the preregistered CFB altitude challenger.

This module only transforms the frozen static elevation snapshot into deterministic
market-blind challenger features. It does not fit, score, rank, select, promote, or
create Model_P. Missing team/venue/elevation/rest evidence fails closed.
"""
from __future__ import annotations

import json
from math import isfinite
from typing import Any, Iterable, Mapping

from .altitude_prereg import EXPECTED_CANDIDATES


class CFBAltitudeFeatureError(ValueError):
    pass


def _int_id(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise CFBAltitudeFeatureError(f"{name}_INVALID")
    try:
        out = int(value)
    except (TypeError, ValueError) as exc:
        raise CFBAltitudeFeatureError(f"{name}_INVALID") from exc
    if out <= 0:
        raise CFBAltitudeFeatureError(f"{name}_INVALID")
    return out


def _elevation_ft(value: Any, name: str) -> float:
    if value is None or isinstance(value, bool):
        raise CFBAltitudeFeatureError(f"{name}_MISSING")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise CFBAltitudeFeatureError(f"{name}_INVALID") from exc
    if not isfinite(out):
        raise CFBAltitudeFeatureError(f"{name}_INVALID")
    return out


def parse_altitude_snapshot_jsonl(snapshot: bytes | str) -> tuple[dict[int, dict[str, Any]], dict[int, dict[str, Any]]]:
    """Parse canonical altitude JSONL into unique team and venue indexes."""
    if isinstance(snapshot, bytes):
        try:
            text = snapshot.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CFBAltitudeFeatureError("ALTITUDE_SNAPSHOT_UTF8_REQUIRED") from exc
    else:
        text = str(snapshot)

    teams: dict[int, dict[str, Any]] = {}
    venues: dict[int, dict[str, Any]] = {}
    saw_row = False
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        saw_row = True
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CFBAltitudeFeatureError(
                f"ALTITUDE_SNAPSHOT_JSON_INVALID:{line_no}"
            ) from exc
        if not isinstance(row, Mapping):
            raise CFBAltitudeFeatureError(f"ALTITUDE_SNAPSHOT_ROW_INVALID:{line_no}")
        entity = str(row.get("entity_type") or "").strip().lower()
        entity_id = _int_id(row.get("id"), "ALTITUDE_ENTITY_ID")
        target = teams if entity == "team" else venues if entity == "venue" else None
        if target is None:
            raise CFBAltitudeFeatureError(
                f"ALTITUDE_ENTITY_TYPE_INVALID:{line_no}:{entity or 'MISSING'}"
            )
        if entity_id in target:
            raise CFBAltitudeFeatureError(f"ALTITUDE_ENTITY_DUPLICATE:{entity}:{entity_id}")
        target[entity_id] = dict(row)

    if not saw_row or not teams or not venues:
        raise CFBAltitudeFeatureError("ALTITUDE_SNAPSHOT_EMPTY_OR_INCOMPLETE")
    return teams, venues


def altitude_delta_ft(
    *,
    teams: Mapping[int, Mapping[str, Any]],
    venues: Mapping[int, Mapping[str, Any]],
    game_venue_id: Any,
    away_team_id: Any,
) -> float:
    """Return max(actual game venue elevation - away home elevation, 0).

    Neutral-site games need no special branch: callers pass the actual target game's
    venue id, so the listed home team's home venue is never substituted.
    """
    venue_id = _int_id(game_venue_id, "ALTITUDE_GAME_VENUE_ID")
    away_id = _int_id(away_team_id, "ALTITUDE_AWAY_TEAM_ID")

    venue = venues.get(venue_id)
    if not isinstance(venue, Mapping):
        raise CFBAltitudeFeatureError(f"ALTITUDE_GAME_VENUE_UNRESOLVED:{venue_id}")
    away = teams.get(away_id)
    if not isinstance(away, Mapping):
        raise CFBAltitudeFeatureError(f"ALTITUDE_AWAY_TEAM_UNRESOLVED:{away_id}")

    game_elevation = _elevation_ft(venue.get("elevation_ft"), "ALTITUDE_GAME_VENUE_ELEVATION")
    location = away.get("location")
    if not isinstance(location, Mapping):
        raise CFBAltitudeFeatureError(f"ALTITUDE_AWAY_HOME_LOCATION_MISSING:{away_id}")
    away_home_venue_id = location.get("id")
    if away_home_venue_id is None:
        raise CFBAltitudeFeatureError(f"ALTITUDE_AWAY_HOME_VENUE_MISSING:{away_id}")
    # Bind through the venue entity rather than silently trusting a duplicate team
    # copy. This preserves one canonical venue-elevation source.
    away_home_venue_id = _int_id(away_home_venue_id, "ALTITUDE_AWAY_HOME_VENUE_ID")
    away_home_venue = venues.get(away_home_venue_id)
    if not isinstance(away_home_venue, Mapping):
        raise CFBAltitudeFeatureError(
            f"ALTITUDE_AWAY_HOME_VENUE_UNRESOLVED:{away_id}:{away_home_venue_id}"
        )
    away_home_elevation = _elevation_ft(
        away_home_venue.get("elevation_ft"),
        "ALTITUDE_AWAY_HOME_VENUE_ELEVATION",
    )
    return max(game_elevation - away_home_elevation, 0.0)


def _rest_days(value: Any) -> int:
    if isinstance(value, bool):
        raise CFBAltitudeFeatureError("ALTITUDE_AWAY_REST_DAYS_INVALID")
    try:
        days = int(value)
    except (TypeError, ValueError) as exc:
        raise CFBAltitudeFeatureError("ALTITUDE_AWAY_REST_DAYS_MISSING") from exc
    if days < 0:
        raise CFBAltitudeFeatureError("ALTITUDE_AWAY_REST_DAYS_INVALID")
    return days


def build_altitude_candidate_features(
    *,
    candidate_id: str,
    altitude_delta: float,
    away_rest_days: Any = None,
) -> dict[str, float]:
    """Apply exactly one frozen challenger formula to a precomputed delta."""
    candidate = str(candidate_id or "").strip()
    if candidate not in EXPECTED_CANDIDATES:
        raise CFBAltitudeFeatureError(f"ALTITUDE_CANDIDATE_UNSUPPORTED:{candidate}")

    delta = float(altitude_delta)
    if not isfinite(delta) or delta < 0:
        raise CFBAltitudeFeatureError("ALTITUDE_DELTA_INVALID")

    if candidate == "altitude_linear_capped_v1":
        return {"altitude_linear_capped_v1": min(delta, 6000.0) / 1000.0}

    if candidate == "altitude_bins_v1":
        return {
            "altitude_bin_0_1000": 1.0 if delta < 1000.0 else 0.0,
            "altitude_bin_1000_3000": 1.0 if 1000.0 <= delta < 3000.0 else 0.0,
            "altitude_bin_3000_plus": 1.0 if delta >= 3000.0 else 0.0,
        }

    days = _rest_days(away_rest_days)
    return {
        "altitude_short_rest_interaction_v1": (
            min(delta, 6000.0) / 1000.0 if days <= 6 else 0.0
        )
    }


def construct_altitude_features(
    *,
    snapshot_records: Iterable[Mapping[str, Any]],
    game_venue_id: Any,
    away_team_id: Any,
    candidate_id: str,
    away_rest_days: Any = None,
) -> dict[str, Any]:
    """Convenience path for already-parsed snapshot rows."""
    teams: dict[int, dict[str, Any]] = {}
    venues: dict[int, dict[str, Any]] = {}
    for raw in snapshot_records:
        row = dict(raw)
        entity = str(row.get("entity_type") or "").strip().lower()
        entity_id = _int_id(row.get("id"), "ALTITUDE_ENTITY_ID")
        target = teams if entity == "team" else venues if entity == "venue" else None
        if target is None:
            raise CFBAltitudeFeatureError(f"ALTITUDE_ENTITY_TYPE_INVALID:{entity}")
        if entity_id in target:
            raise CFBAltitudeFeatureError(f"ALTITUDE_ENTITY_DUPLICATE:{entity}:{entity_id}")
        target[entity_id] = row
    if not teams or not venues:
        raise CFBAltitudeFeatureError("ALTITUDE_SNAPSHOT_EMPTY_OR_INCOMPLETE")

    delta = altitude_delta_ft(
        teams=teams,
        venues=venues,
        game_venue_id=game_venue_id,
        away_team_id=away_team_id,
    )
    return {
        "altitude_delta_ft": delta,
        "candidate_id": candidate_id,
        "features": build_altitude_candidate_features(
            candidate_id=candidate_id,
            altitude_delta=delta,
            away_rest_days=away_rest_days,
        ),
        "fit_performed": False,
        "evaluation_performed": False,
        "attempt_consumed": False,
        "model_p_created": False,
        "promotion_authority": False,
        "official_authority": False,
    }


__all__ = [
    "CFBAltitudeFeatureError",
    "altitude_delta_ft",
    "build_altitude_candidate_features",
    "construct_altitude_features",
    "parse_altitude_snapshot_jsonl",
]
