from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any, Mapping

SOURCE = "BALLPARKPAL_STARTER_BULLPEN_REPORT"
SOURCE_ROLE = "CONTEXT_ONLY"
MODEL_VOTE = False
CONTEXT_CLASS = "starter_bullpen_projection"

_STAT_KEYS = ("ip", "runs", "hits", "hr", "k", "bb")
_FLAG_KEYS = ("opener_flag", "bulk_pitcher_flag", "short_leash_flag")


class BallparkPalContextError(ValueError):
    pass


def _nonnegative_number(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise BallparkPalContextError(f"{field} must be a finite nonnegative number")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise BallparkPalContextError(f"{field} must be a finite nonnegative number") from exc
    if not isfinite(out) or out < 0:
        raise BallparkPalContextError(f"{field} must be a finite nonnegative number")
    return out


def _optional_observed_at(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError as exc:
            raise BallparkPalContextError("observed_at_utc must be an ISO-8601 timestamp") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise BallparkPalContextError("observed_at_utc must be timezone-aware")
    return dt.astimezone(timezone.utc).isoformat()


def _normalize_side(side: str, row: Mapping[str, Any]) -> dict[str, Any]:
    starter = row.get("starter")
    bullpen = row.get("bullpen")
    if not isinstance(starter, Mapping) or not isinstance(bullpen, Mapping):
        raise BallparkPalContextError(f"{side} requires starter and bullpen mappings")

    starter_name = str(starter.get("name") or "").strip()
    if not starter_name:
        raise BallparkPalContextError(f"{side}.starter.name is required")

    starter_stats = {
        key: _nonnegative_number(starter.get(key), f"{side}.starter.{key}")
        for key in _STAT_KEYS
    }
    bullpen_stats = {
        key: _nonnegative_number(bullpen.get(key), f"{side}.bullpen.{key}")
        for key in _STAT_KEYS
    }

    projected_pitching_ip = starter_stats["ip"] + bullpen_stats["ip"]
    bullpen_share = (
        bullpen_stats["ip"] / projected_pitching_ip
        if projected_pitching_ip > 0
        else 0.0
    )

    flags: dict[str, bool] = {}
    for key in _FLAG_KEYS:
        value = row.get(key, False)
        if not isinstance(value, bool):
            raise BallparkPalContextError(f"{side}.{key} must be boolean")
        flags[key] = value

    return {
        "team": str(row.get("team") or "").strip() or None,
        "starter_name": starter_name,
        "starter_projected_ip": starter_stats["ip"],
        "starter_projected_runs": starter_stats["runs"],
        "starter_projected_hits": starter_stats["hits"],
        "starter_projected_hr": starter_stats["hr"],
        "starter_projected_k": starter_stats["k"],
        "starter_projected_bb": starter_stats["bb"],
        "bullpen_projected_ip": bullpen_stats["ip"],
        "bullpen_projected_runs": bullpen_stats["runs"],
        "bullpen_projected_hits": bullpen_stats["hits"],
        "bullpen_projected_hr": bullpen_stats["hr"],
        "bullpen_projected_k": bullpen_stats["k"],
        "bullpen_projected_bb": bullpen_stats["bb"],
        "projected_pitching_ip": projected_pitching_ip,
        "projected_total_runs_allowed": starter_stats["runs"] + bullpen_stats["runs"],
        "bullpen_share": bullpen_share,
        "bullpen_heavy_flag": bullpen_share >= 0.5,
        **flags,
    }


def normalize_ballparkpal_report(
    report: Mapping[str, Any],
    *,
    expected_game_pk: int | None = None,
) -> dict[str, Any]:
    """Normalize one BallparkPal starter x bullpen report as context-only evidence.

    BallparkPal is never a Model_P input or Truth-Gate vote. The normalized payload
    is intended to flag opener/bulk usage, short starter leashes, bullpen share and
    projected run prevention for comparison against SportsEdge's own projections.
    """
    if not isinstance(report, Mapping):
        raise BallparkPalContextError("report must be a mapping")
    try:
        game_pk = int(report["game_pk"])
    except (KeyError, TypeError, ValueError) as exc:
        raise BallparkPalContextError("game_pk is required") from exc
    if game_pk <= 0:
        raise BallparkPalContextError("game_pk must be positive")
    if expected_game_pk is not None and game_pk != int(expected_game_pk):
        raise BallparkPalContextError(
            f"game identity mismatch: report game_pk={game_pk}, expected={int(expected_game_pk)}"
        )

    teams = report.get("teams")
    if not isinstance(teams, Mapping):
        raise BallparkPalContextError("teams mapping is required")
    away = teams.get("away")
    home = teams.get("home")
    if not isinstance(away, Mapping) or not isinstance(home, Mapping):
        raise BallparkPalContextError("teams.away and teams.home are required")

    normalized = {
        "source": SOURCE,
        "source_role": SOURCE_ROLE,
        "context_class": CONTEXT_CLASS,
        "model_p_eligible": MODEL_VOTE,
        "truth_gate_eligible": False,
        "game_pk": game_pk,
        "observed_at_utc": _optional_observed_at(report.get("observed_at_utc")),
        "source_url": str(report.get("source_url") or "").strip() or None,
        "away": _normalize_side("away", away),
        "home": _normalize_side("home", home),
    }
    normalized["projected_game_runs"] = (
        normalized["away"]["projected_total_runs_allowed"]
        + normalized["home"]["projected_total_runs_allowed"]
    )
    return normalized


def build_ballparkpal_provider(report: Mapping[str, Any]):
    """Return a provider compatible with collect_mlb_hybrid_context()."""

    def provider(game_pk: int, as_of: datetime, live_payload: Mapping[str, Any]) -> dict[str, Any]:
        # game_pk is the canonical identity. We intentionally do not infer a different
        # matchup from names/abbreviations supplied by a screenshot or third party.
        return normalize_ballparkpal_report(report, expected_game_pk=game_pk)

    return provider
