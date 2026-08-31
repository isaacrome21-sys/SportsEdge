from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Mapping

from .context_autopull import ContextObservation, NFLContextError, run_context_mode
from .context_providers import build_rest_travel_provider, build_workload_leash_provider
from .context_source_adapters import official_injury_auto_adapter, weather_roof_auto_adapter
from .defensive_context import build_defensive_matchup_provider
from .personnel_coaching_context import build_coaching_provider, build_personnel_provider
from .special_teams_context import build_special_teams_provider
from .stadium_registry import load_default_stadium_registry, registry_sha256


def build_default_auto_providers(*, game: Mapping[str, Any]) -> dict[str, Any]:
    """Build provider closures for NFL AUTO objective context.

    Missing objective inputs return None and become explicit MISSING observations.
    This registry contains no social/public-betting/sportsbook inputs.
    """
    def venue_surface(game_id: str, pit: datetime):
        stadium_id = str(game.get("stadium_id") or "").strip()
        if not stadium_id:
            return None
        registry = load_default_stadium_registry()
        stadium = registry.get(stadium_id)
        if stadium is None:
            return None
        payload = {
            "game_id": game_id,
            "stadium_id": stadium.stadium_id,
            "name": stadium.name,
            "team_ids": list(stadium.team_ids),
            "lat": stadium.lat,
            "lon": stadium.lon,
            "field_bearing_deg": stadium.field_bearing_deg,
            "roof_type": stadium.roof_type,
            "timezone": stadium.timezone_name,
            "typical_home_kickoff_hour_local": stadium.typical_home_kickoff_hour_local,
            "surface_type": game.get("surface_type"),
            "altitude_ft": game.get("altitude_ft"),
        }
        return {
            "status": "AVAILABLE",
            "payload": payload,
            "source_name": "SPORTSEDGE_STADIUM_REGISTRY",
            "source_uri": "https://github.com/isaacrome21-sys/SportsEdge",
            "source_sha256": registry_sha256(registry),
            "observed_at": pit,
        }

    def weather(game_id: str, pit: datetime):
        stadium_id = game.get("stadium_id")
        kickoff = game.get("kickoff_ts")
        if not stadium_id or kickoff is None:
            return None
        return weather_roof_auto_adapter(
            game_id=game_id,
            stadium_id=str(stadium_id),
            kickoff=kickoff,
            as_of=pit,
            authoritative_roof=game.get("authoritative_roof"),
        )

    def injury(game_id: str, pit: datetime):
        rows = list(game.get("official_injury_rows") or [])
        if not rows:
            return None
        observations = [official_injury_auto_adapter(
            game_id=game_id,
            team_id=str(raw.get("team_id") or ""),
            player_id=str(raw.get("player_id") or ""),
            as_of=pit,
            source_uri=str(raw.get("source_uri") or ""),
            source_payload=dict(raw.get("source_payload") or {}),
        ) for raw in rows]
        from ...source_lineage import canonical_json_sha256
        return {
            "status": "AVAILABLE",
            "payload": [row["payload"] for row in observations],
            "source_name": "OFFICIAL_NFL_INJURY_REPORTS",
            "source_uri": observations[-1]["source_uri"],
            "source_sha256": canonical_json_sha256(sorted(row["source_sha256"] for row in observations)),
            "observed_at": pit,
        }

    def rest_travel(game_id: str, pit: datetime):
        rows = game.get("rest_travel_inputs")
        if not isinstance(rows, Mapping) or not rows:
            return None
        payload, hashes, source_uri = {}, [], None
        for team_id, source_payload in rows.items():
            row = build_rest_travel_provider(game_id=game_id, team_id=str(team_id), as_of=pit,
                source_uri=str(source_payload.get("source_uri") or ""), source_payload=dict(source_payload))
            payload[str(team_id)] = row["payload"]
            hashes.append(row["source_sha256"]); source_uri = row["source_uri"]
        from ...source_lineage import canonical_json_sha256
        return {"status":"AVAILABLE","payload":payload,"source_name":"NFL_SCHEDULE+STADIUM_REGISTRY",
                "source_uri":str(source_uri),"source_sha256":canonical_json_sha256(sorted(hashes)),"observed_at":pit}

    def workload_rows(game_id: str, pit: datetime):
        rows = list(game.get("workload_inputs") or [])
        if not rows:
            return None
        payload, hashes, source_uri = [], [], None
        for raw in rows:
            row = build_workload_leash_provider(game_id=game_id, player_id=str(raw.get("player_id") or ""),
                team_id=str(raw.get("team_id") or ""), as_of=pit, source_uri=str(raw.get("source_uri") or ""),
                source_payload=dict(raw.get("source_payload") or {}), injury_ramp_state=raw.get("injury_ramp_state"),
                short_week=raw.get("short_week"))
            payload.append(row["payload"]); hashes.append(row["source_sha256"]); source_uri = row["source_uri"]
        from ...source_lineage import canonical_json_sha256
        return {"status":"AVAILABLE","payload":payload,"source_name":"PIT_SNAP_USAGE_WORKLOAD",
                "source_uri":str(source_uri),"source_sha256":canonical_json_sha256(sorted(hashes)),"observed_at":pit}

    def snap_usage(game_id: str, pit: datetime):
        return workload_rows(game_id, pit)

    def workload(game_id: str, pit: datetime):
        return workload_rows(game_id, pit)

    def defensive(game_id: str, pit: datetime):
        rows = list(game.get("defensive_matchup_inputs") or [])
        if not rows:
            return None
        payload, hashes, source_uri = [], [], None
        for raw in rows:
            row = build_defensive_matchup_provider(game_id=game_id,
                offense_team_id=str(raw.get("offense_team_id") or ""), defense_team_id=str(raw.get("defense_team_id") or ""),
                as_of=pit, source_uri=str(raw.get("source_uri") or ""), source_sha256=str(raw.get("source_sha256") or ""),
                splits=list(raw.get("splits") or []))
            payload.append(row["payload"]); hashes.append(row["source_sha256"]); source_uri = row["source_uri"]
        from ...source_lineage import canonical_json_sha256
        return {"status":"AVAILABLE","payload":payload,"source_name":"PIT_DEFENSIVE_SPLITS",
                "source_uri":str(source_uri),"source_sha256":canonical_json_sha256(sorted(hashes)),"observed_at":pit}

    def personnel(game_id: str, pit: datetime):
        rows = list(game.get("personnel_package_inputs") or [])
        if not rows:
            return None
        return build_personnel_provider(game_id=game_id, as_of=pit,
            source_uri=str(game.get("personnel_source_uri") or ""), source_sha256=str(game.get("personnel_source_sha256") or ""), rows=rows)

    def special_teams(game_id: str, pit: datetime):
        rows = list(game.get("special_teams_inputs") or [])
        if not rows:
            return None
        return build_special_teams_provider(game_id=game_id, as_of=pit,
            source_uri=str(game.get("special_teams_source_uri") or ""), source_sha256=str(game.get("special_teams_source_sha256") or ""), rows=rows)

    def coaching(game_id: str, pit: datetime):
        rows = list(game.get("coaching_tendency_inputs") or [])
        if not rows:
            return None
        return build_coaching_provider(game_id=game_id, as_of=pit,
            source_uri=str(game.get("coaching_source_uri") or ""), source_sha256=str(game.get("coaching_source_sha256") or ""), rows=rows)

    return {
        "venue_surface": venue_surface,
        "weather": weather,
        "rest_travel": rest_travel,
        "injury_availability": injury,
        "snap_usage_workload": snap_usage,
        "personnel_packages": personnel,
        "defensive_matchup": defensive,
        "special_teams": special_teams,
        "coaching_tendencies": coaching,
        "workload_leash": workload,
    }


def build_run_it_context(*, mode: str, game: Mapping[str, Any], as_of: Any, manual_observations: Iterable[ContextObservation] | None = None) -> dict[str, Any]:
    game_id = str(game.get("game_id") or "").strip()
    if not game_id:
        raise NFLContextError("RUN IT game_id required")
    return run_context_mode(mode=mode, game_id=game_id, as_of=as_of,
        providers=build_default_auto_providers(game=game), manual_observations=list(manual_observations or []))
