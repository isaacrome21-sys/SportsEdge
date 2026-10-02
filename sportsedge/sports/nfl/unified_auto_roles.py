from __future__ import annotations

"""Assemble unified NFL team models from PIT-safe nflverse role/depth inputs."""

from datetime import datetime, timezone
import re
from typing import Any, Mapping, Sequence

from .context_autopull import NFLContextError
from .nflverse_role_bridge import build_nflverse_prop_role_payloads

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TEAM_ALIASES = {"LA": "LAR", "WSH": "WAS"}
_SKILL_POSITIONS = frozenset({"RB", "FB", "WR", "TE"})


def _team(value: Any) -> str:
    raw = str(value or "").strip().upper()
    return _TEAM_ALIASES.get(raw, raw)


def _utc(value: Any, field: str) -> datetime:
    try:
        out = value if isinstance(value, datetime) else datetime.fromisoformat(
            str(value or "").strip().replace("Z", "+00:00")
        )
    except (TypeError, ValueError) as exc:
        raise NFLContextError(f"{field} invalid") from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise NFLContextError(f"{field} timezone required")
    return out.astimezone(timezone.utc)


def _rank_one(value: Any) -> bool:
    try:
        return int(float(value)) == 1
    except (TypeError, ValueError):
        return False


def _validate_depth_provenance(source_uri: str, source_sha256: str) -> None:
    if not str(source_uri or "").startswith("https://"):
        raise NFLContextError("depth source_uri must be https")
    digest = str(source_sha256 or "").strip().lower()
    if not _SHA256.fullmatch(digest):
        raise NFLContextError("depth source_sha256 invalid")


def _latest_depth_snapshot(
    *,
    rows: Sequence[Mapping[str, Any]],
    team: str,
    as_of: datetime,
) -> tuple[datetime, list[dict[str, Any]]]:
    eligible: list[tuple[datetime, dict[str, Any]]] = []
    for raw in rows:
        row = dict(raw)
        if _team(row.get("team") or row.get("club_code")) != team:
            continue
        if row.get("dt") in (None, ""):
            continue
        stamp = _utc(row.get("dt"), "depth dt")
        if stamp <= as_of:
            eligible.append((stamp, row))
    if not eligible:
        raise NFLContextError(f"depth snapshot missing:{team}")
    latest = max(stamp for stamp, _ in eligible)
    return latest, [row for stamp, row in eligible if stamp == latest]


def _starter_qb_id(snapshot: Sequence[Mapping[str, Any]], team: str) -> str:
    ids: set[str] = set()
    for row in snapshot:
        position = str(
            row.get("pos_abb") or row.get("position") or row.get("pos_name") or ""
        ).strip().upper()
        if position not in {"QB", "QUARTERBACK"} or not _rank_one(row.get("pos_rank")):
            continue
        player_id = str(row.get("gsis_id") or "").strip()
        if player_id:
            ids.add(player_id)
    if len(ids) != 1:
        raise NFLContextError(f"starting QB identity not unique:{team}")
    return next(iter(ids))


def _assemble_team(
    *,
    team: str,
    starter_qb_id: str,
    role_bundle: Mapping[str, Any],
) -> dict[str, Any]:
    players = [
        dict(row)
        for row in role_bundle.get("players", [])
        if isinstance(row, Mapping) and _team(row.get("team")) == team
    ]
    qb_matches = [
        row for row in players
        if str(row.get("player_id") or "").strip() == starter_qb_id
        and str(row.get("position") or "").strip().upper() == "QB"
    ]
    if len(qb_matches) != 1:
        raise NFLContextError(f"starter QB role row missing:{team}:{starter_qb_id}")

    skills = [
        row for row in players
        if str(row.get("position") or "").strip().upper() in _SKILL_POSITIONS
    ]
    if not skills:
        raise NFLContextError(f"skill-player role rows missing:{team}")

    scoring = role_bundle.get("team_scoring")
    if not isinstance(scoring, Mapping):
        raise NFLContextError("team_scoring missing from role bundle")
    scoring_row = scoring.get(team)
    if not isinstance(scoring_row, Mapping):
        raise NFLContextError(f"team scoring missing:{team}")
    pass_td_share = scoring_row.get("pass_td_share")
    if pass_td_share is not None:
        try:
            pass_td_share = float(pass_td_share)
        except (TypeError, ValueError) as exc:
            raise NFLContextError(f"pass_td_share invalid:{team}") from exc
        if not 0.0 <= pass_td_share <= 1.0:
            raise NFLContextError(f"pass_td_share out of range:{team}")

    return {
        "qb": qb_matches[0],
        "skill_players": skills,
        "pass_td_share": pass_td_share,
    }


def assemble_unified_team_models(
    *,
    role_bundle: Mapping[str, Any],
    depth_rows: Sequence[Mapping[str, Any]],
    depth_source_uri: str,
    depth_source_sha256: str,
    as_of: Any,
    home_team: str,
    away_team: str,
) -> dict[str, Any]:
    """Bind current PIT depth starters to strict-prior empirical player roles."""
    if not isinstance(role_bundle, Mapping) or role_bundle.get("status") != "AVAILABLE":
        raise NFLContextError("AVAILABLE role bundle required")
    _validate_depth_provenance(depth_source_uri, depth_source_sha256)
    pit = _utc(as_of, "as_of")
    observed = _utc(role_bundle.get("observed_at"), "role_bundle.observed_at")
    if observed > pit:
        raise NFLContextError("role bundle observed after assembly as_of")

    home = _team(home_team)
    away = _team(away_team)
    if not home or not away or home == away:
        raise NFLContextError("home/away team identity invalid")

    materialized = [dict(row) for row in depth_rows]
    snapshots: dict[str, str] = {}
    starters: dict[str, str] = {}
    for team in (home, away):
        stamp, snapshot = _latest_depth_snapshot(rows=materialized, team=team, as_of=pit)
        snapshots[team] = stamp.isoformat()
        starters[team] = _starter_qb_id(snapshot, team)

    return {
        "status": "AVAILABLE",
        "home_team": home,
        "away_team": away,
        "home_model": _assemble_team(
            team=home, starter_qb_id=starters[home], role_bundle=role_bundle
        ),
        "away_model": _assemble_team(
            team=away, starter_qb_id=starters[away], role_bundle=role_bundle
        ),
        "starter_qb_id_by_team": starters,
        "depth_snapshot_asof_by_team": snapshots,
        "provenance": {
            "role_source_uri": role_bundle.get("source_uri"),
            "role_source_raw_sha256": role_bundle.get("source_raw_sha256"),
            "role_normalized_rows_sha256": role_bundle.get("normalized_rows_sha256"),
            "depth_source_uri": depth_source_uri,
            "depth_source_sha256": depth_source_sha256,
        },
        "authority": "RESEARCH_ONLY / NOT Model_P / NOT Truth Gate / NOT OFFICIAL",
    }


def build_unified_team_models_from_nflverse(
    *,
    game_id: str,
    kickoff: Any,
    observed_at: Any,
    source_binding: Mapping[str, Any],
    player_rows: Sequence[Mapping[str, Any]],
    depth_rows: Sequence[Mapping[str, Any]],
    depth_source_uri: str,
    depth_source_sha256: str,
    as_of: Any,
    home_team: str,
    away_team: str,
) -> dict[str, Any]:
    role_bundle = build_nflverse_prop_role_payloads(
        game_id=game_id,
        kickoff=kickoff,
        observed_at=observed_at,
        source_binding=source_binding,
        player_rows=player_rows,
    )
    return assemble_unified_team_models(
        role_bundle=role_bundle,
        depth_rows=depth_rows,
        depth_source_uri=depth_source_uri,
        depth_source_sha256=depth_source_sha256,
        as_of=as_of,
        home_team=home_team,
        away_team=away_team,
    )


__all__ = [
    "assemble_unified_team_models",
    "build_unified_team_models_from_nflverse",
]
