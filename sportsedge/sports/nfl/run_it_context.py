from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Mapping

from .context_autopull import ContextObservation, NFLContextError, run_context_mode
from .context_providers import build_rest_travel_provider, build_workload_leash_provider
from .context_source_adapters import official_injury_auto_adapter, weather_roof_auto_adapter


def build_default_auto_providers(*, game: Mapping[str, Any]) -> dict[str, Any]:
    """Build provider closures for the four first-class NFL AUTO sources.

    Inputs are already-resolved objective snapshots supplied by the NFL runtime.
    Missing snapshots return None so the shared collector emits explicit MISSING.
    """
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
        observations = []
        for raw in rows:
            observations.append(official_injury_auto_adapter(
                game_id=game_id,
                team_id=str(raw.get("team_id") or ""),
                player_id=str(raw.get("player_id") or ""),
                as_of=pit,
                source_uri=str(raw.get("source_uri") or ""),
                source_payload=dict(raw.get("source_payload") or {}),
            ))
        return {
            "status": "AVAILABLE",
            "payload": [row["payload"] for row in observations],
            "source_name": "OFFICIAL_NFL_INJURY_REPORTS",
            "source_uri": observations[-1]["source_uri"],
            "source_sha256": observations[-1]["source_sha256"],
            "observed_at": pit,
        }

    def rest_travel(game_id: str, pit: datetime):
        rows = game.get("rest_travel_inputs")
        if not isinstance(rows, Mapping) or not rows:
            return None
        payload = {}
        hashes = []
        source_uri = None
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
        from ...source_lineage import canonical_json_sha256
        return {
            "status": "AVAILABLE",
            "payload": payload,
            "source_name": "NFL_SCHEDULE+STADIUM_REGISTRY",
            "source_uri": str(source_uri),
            "source_sha256": canonical_json_sha256(sorted(hashes)),
            "observed_at": pit,
        }

    def workload(game_id: str, pit: datetime):
        rows = list(game.get("workload_inputs") or [])
        if not rows:
            return None
        payload = []
        hashes = []
        source_uri = None
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
        from ...source_lineage import canonical_json_sha256
        return {
            "status": "AVAILABLE",
            "payload": payload,
            "source_name": "PIT_SNAP_USAGE_WORKLOAD",
            "source_uri": str(source_uri),
            "source_sha256": canonical_json_sha256(sorted(hashes)),
            "observed_at": pit,
        }

    return {
        "weather": weather,
        "injury_availability": injury,
        "rest_travel": rest_travel,
        "workload_leash": workload,
    }


def build_run_it_context(*, mode: str, game: Mapping[str, Any], as_of: Any, manual_observations: Iterable[ContextObservation] | None = None) -> dict[str, Any]:
    game_id = str(game.get("game_id") or "").strip()
    if not game_id:
        raise NFLContextError("RUN IT game_id required")
    providers = build_default_auto_providers(game=game)
    return run_context_mode(
        mode=mode,
        game_id=game_id,
        as_of=as_of,
        providers=providers,
        manual_observations=list(manual_observations or []),
    )
