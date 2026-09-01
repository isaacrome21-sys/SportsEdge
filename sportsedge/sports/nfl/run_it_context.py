from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Iterable, Mapping
from urllib.request import urlopen

from ...source_lineage import canonical_json_sha256
from .auto_context_source import build_nfl_auto_game_context
from .context_autopull import ContextObservation, NFLContextError, run_context_mode
from .context_providers import build_rest_travel_provider, build_workload_leash_provider
from .context_source_adapters import official_injury_auto_adapter, weather_roof_auto_adapter
from .defensive_context import build_defensive_matchup_provider
from .personnel_coaching_context import build_coaching_provider, build_personnel_provider
from .prop_opportunity_context import build_prop_opportunity_provider
from .special_teams_context import build_special_teams_provider
from .stadium_registry import load_stadium_registry


def _valid_sha(value: Any) -> str | None:
    raw = str(value or "").strip().lower()
    if len(raw) != 64:
        return None
    try:
        int(raw, 16)
    except ValueError:
        return None
    return raw


def build_default_auto_providers(
    *,
    game: Mapping[str, Any],
    opener: Callable = urlopen,
) -> dict[str, Any]:
    """Build provider closures for NFL AUTO objective context.

    Missing objective inputs return None and become explicit MISSING observations.
    This registry contains no social/public-betting/sportsbook inputs.
    """
    def venue_surface(game_id: str, pit: datetime):
        stadium_id = str(game.get("stadium_id") or "").strip()
        if not stadium_id:
            return None
        registry = load_stadium_registry()
        stadium = (registry.get("stadiums") or {}).get(stadium_id)
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
            "registry_version": registry.get("version"),
            "schedule_source_uri": game.get("schedule_source_uri"),
            "schedule_source_sha256": game.get("schedule_source_sha256"),
        }
        hashes = [str(registry.get("registry_sha256") or "")]
        schedule_sha = _valid_sha(game.get("schedule_source_sha256"))
        if schedule_sha is not None:
            hashes.append(schedule_sha)
        return {
            "status": "AVAILABLE",
            "payload": payload,
            "source_name": "SPORTSEDGE_STADIUM_REGISTRY"
            + ("+NFLVERSE_SCHEDULE" if schedule_sha is not None else ""),
            "source_uri": str(
                game.get("schedule_source_uri")
                or "https://github.com/isaacrome21-sys/SportsEdge"
            ),
            "source_sha256": (
                canonical_json_sha256(sorted(hashes))
                if len(hashes) > 1
                else hashes[0]
            ),
            "observed_at": pit,
        }

    def weather(game_id: str, pit: datetime):
        stadium_id = game.get("stadium_id")
        kickoff = game.get("kickoff_ts")
        if not stadium_id or kickoff is None:
            return None
        row = dict(
            weather_roof_auto_adapter(
                game_id=game_id,
                stadium_id=str(stadium_id),
                kickoff=kickoff,
                as_of=pit,
                authoritative_roof=game.get("authoritative_roof"),
                opener=opener,
            )
        )
        schedule_sha = _valid_sha(game.get("schedule_source_sha256"))
        if schedule_sha is not None:
            payload = dict(row.get("payload") or {})
            payload["kickoff_source_uri"] = game.get("schedule_source_uri")
            payload["kickoff_source_sha256"] = schedule_sha
            row["payload"] = payload
            row["source_name"] = str(row.get("source_name") or "NWS_HOURLY") + "+NFLVERSE_SCHEDULE"
            row["source_sha256"] = canonical_json_sha256(
                sorted([str(row.get("source_sha256") or ""), schedule_sha])
            )
        return row

    def injury(game_id: str, pit: datetime):
        rows = list(game.get("official_injury_rows") or [])
        if not rows:
            return None
        observations = [
            official_injury_auto_adapter(
                game_id=game_id,
                team_id=str(raw.get("team_id") or ""),
                player_id=str(raw.get("player_id") or ""),
                as_of=pit,
                source_uri=str(raw.get("source_uri") or ""),
                source_payload=dict(raw.get("source_payload") or {}),
            )
            for raw in rows
        ]
        return {
            "status": "AVAILABLE",
            "payload": [row["payload"] for row in observations],
            "source_name": "OFFICIAL_NFL_INJURY_REPORTS",
            "source_uri": observations[-1]["source_uri"],
            "source_sha256": canonical_json_sha256(
                sorted(row["source_sha256"] for row in observations)
            ),
            "observed_at": pit,
        }

    def rest_travel(game_id: str, pit: datetime):
        auto_row = game.get("auto_rest_travel_provider")
        if isinstance(auto_row, Mapping) and auto_row:
            row = dict(auto_row)
            row["observed_at"] = pit
            return row
        rows = game.get("rest_travel_inputs")
        if not isinstance(rows, Mapping) or not rows:
            return None
        payload, hashes, source_uri = {}, [], None
        for team_id, source_payload in rows.items():
            row = build_rest_travel_provider(
                game_id=game_id,
                team_id=str(team_id),
                as_of=pit,
                source_uri=str(source_payload.get("source_uri") or ""),
                source_payload=dict(source_payload),
            )
            payload[str(team_id)] = row["payload"]
            hashes.append(row["source_sha256"])
            source_uri = row["source_uri"]
        return {
            "status": "AVAILABLE",
            "payload": payload,
            "source_name": "NFL_SCHEDULE+STADIUM_REGISTRY",
            "source_uri": str(source_uri),
            "source_sha256": canonical_json_sha256(sorted(hashes)),
            "observed_at": pit,
        }

    def workload_rows(game_id: str, pit: datetime):
        rows = list(game.get("workload_inputs") or [])
        if not rows:
            return None
        payload, hashes, source_uri = [], [], None
        for raw in rows:
            row = build_workload_leash_provider(
                game_id=game_id,
                player_id=str(raw.get("player_id") or ""),
                team_id=str(raw.get("team_id") or ""),
                as_of=pit,
                source_uri=str(raw.get("source_uri") or ""),
                source_payload=dict(raw.get("source_payload") or {}),
                injury_ramp_state=raw.get("injury_ramp_state"),
                short_week=raw.get("short_week"),
            )
            payload.append(row["payload"])
            hashes.append(row["source_sha256"])
            source_uri = row["source_uri"]
        return {
            "status": "AVAILABLE",
            "payload": payload,
            "source_name": "PIT_SNAP_USAGE_WORKLOAD",
            "source_uri": str(source_uri),
            "source_sha256": canonical_json_sha256(sorted(hashes)),
            "observed_at": pit,
        }

    def snap_usage(game_id: str, pit: datetime):
        prop_rows = list(game.get("prop_opportunity_inputs") or [])
        workload = workload_rows(game_id, pit)
        if not prop_rows:
            return workload
        prop = build_prop_opportunity_provider(
            game_id=game_id,
            as_of=pit,
            source_uri=str(game.get("prop_opportunity_source_uri") or ""),
            source_sha256=str(game.get("prop_opportunity_source_sha256") or ""),
            rows=prop_rows,
        )
        if workload is None:
            return prop
        return {
            "status": "AVAILABLE",
            "payload": {
                "workload": workload["payload"],
                "prop_opportunity": prop["payload"],
            },
            "source_name": "PIT_SNAP_USAGE_WORKLOAD+PROP_OPPORTUNITY",
            "source_uri": prop["source_uri"],
            "source_sha256": canonical_json_sha256(
                sorted([workload["source_sha256"], prop["source_sha256"]])
            ),
            "observed_at": pit,
        }

    def workload(game_id: str, pit: datetime):
        return workload_rows(game_id, pit)

    def defensive(game_id: str, pit: datetime):
        rows = list(game.get("defensive_matchup_inputs") or [])
        if not rows:
            return None
        payload, hashes, source_uri = [], [], None
        for raw in rows:
            row = build_defensive_matchup_provider(
                game_id=game_id,
                offense_team_id=str(raw.get("offense_team_id") or ""),
                defense_team_id=str(raw.get("defense_team_id") or ""),
                as_of=pit,
                source_uri=str(raw.get("source_uri") or ""),
                source_sha256=str(raw.get("source_sha256") or ""),
                splits=list(raw.get("splits") or []),
            )
            payload.append(row["payload"])
            hashes.append(row["source_sha256"])
            source_uri = row["source_uri"]
        return {
            "status": "AVAILABLE",
            "payload": payload,
            "source_name": "PIT_DEFENSIVE_SPLITS",
            "source_uri": str(source_uri),
            "source_sha256": canonical_json_sha256(sorted(hashes)),
            "observed_at": pit,
        }

    def personnel(game_id: str, pit: datetime):
        auto_row = game.get("auto_personnel_provider")
        if isinstance(auto_row, Mapping) and auto_row:
            row = dict(auto_row)
            row["observed_at"] = pit
            return row
        rows = list(game.get("personnel_package_inputs") or [])
        if not rows:
            return None
        return build_personnel_provider(
            game_id=game_id,
            as_of=pit,
            source_uri=str(game.get("personnel_source_uri") or ""),
            source_sha256=str(game.get("personnel_source_sha256") or ""),
            rows=rows,
        )

    def special_teams(game_id: str, pit: datetime):
        rows = list(game.get("special_teams_inputs") or [])
        if not rows:
            return None
        return build_special_teams_provider(
            game_id=game_id,
            as_of=pit,
            source_uri=str(game.get("special_teams_source_uri") or ""),
            source_sha256=str(game.get("special_teams_source_sha256") or ""),
            rows=rows,
        )

    def coaching(game_id: str, pit: datetime):
        rows = list(game.get("coaching_tendency_inputs") or [])
        if not rows:
            return None
        return build_coaching_provider(
            game_id=game_id,
            as_of=pit,
            source_uri=str(game.get("coaching_source_uri") or ""),
            source_sha256=str(game.get("coaching_source_sha256") or ""),
            rows=rows,
        )

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


def build_run_it_context(
    *,
    mode: str,
    game: Mapping[str, Any],
    as_of: Any,
    manual_observations: Iterable[ContextObservation] | None = None,
    opener: Callable = urlopen,
) -> dict[str, Any]:
    game_id = str(game.get("game_id") or "").strip()
    if not game_id:
        raise NFLContextError("RUN IT game_id required")
    return run_context_mode(
        mode=mode,
        game_id=game_id,
        as_of=as_of,
        providers=build_default_auto_providers(game=game, opener=opener),
        manual_observations=list(manual_observations or []),
    )


def build_run_it_context_from_sources(
    *,
    mode: str,
    game_id: str,
    as_of: Any,
    manual_observations: Iterable[ContextObservation] | None = None,
    opener: Callable = urlopen,
) -> dict[str, Any]:
    """Canonical source-driven RUN IT context entry point.

    AUTO and HYBRID resolve schedule, team, venue, surface, kickoff, weather and
    rest/travel inputs without operator prefill. MANUAL deliberately performs no
    network acquisition. Context classes without a trusted wired source remain
    explicit MISSING; none are inferred from betting markets or social inputs.
    """
    requested = str(mode).upper().strip()
    if requested == "MANUAL":
        return build_run_it_context(
            mode=requested,
            game={"game_id": str(game_id)},
            as_of=as_of,
            manual_observations=manual_observations,
            opener=opener,
        )
    if requested not in {"AUTO", "HYBRID"}:
        raise NFLContextError(f"invalid collection mode: {requested}")
    game = build_nfl_auto_game_context(
        game_id=str(game_id),
        as_of=as_of,
        opener=opener,
    )
    return build_run_it_context(
        mode=requested,
        game=game,
        as_of=as_of,
        manual_observations=manual_observations,
        opener=opener,
    )
