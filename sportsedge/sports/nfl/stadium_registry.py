from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

from .context_autopull import NFLContextError
from .context_providers import StadiumRecord

REGISTRY_FILENAME = "stadiums_2026.json"


def load_stadium_registry(path: str | Path | None = None) -> dict[str, Any]:
    registry_path = Path(path) if path is not None else Path(__file__).with_name(REGISTRY_FILENAME)
    raw = registry_path.read_bytes()
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise NFLContextError("stadium registry invalid JSON") from exc

    version = str(parsed.get("version") or "").strip()
    rows = parsed.get("stadiums")
    if not version or not isinstance(rows, list) or not rows:
        raise NFLContextError("stadium registry missing version/stadiums")

    stadiums: dict[str, StadiumRecord] = {}
    team_to_stadium: dict[str, str] = {}
    for raw_row in rows:
        if not isinstance(raw_row, Mapping):
            raise NFLContextError("stadium registry row invalid")
        row = StadiumRecord(
            stadium_id=str(raw_row.get("stadium_id") or ""),
            name=str(raw_row.get("name") or ""),
            team_ids=tuple(str(x) for x in (raw_row.get("team_ids") or [])),
            lat=float(raw_row.get("lat")),
            lon=float(raw_row.get("lon")),
            field_bearing_deg=float(raw_row.get("field_bearing_deg")),
            roof_type=str(raw_row.get("roof_type") or ""),
            timezone_name=str(raw_row.get("timezone") or ""),
            typical_home_kickoff_hour_local=float(raw_row.get("typical_home_kickoff_hour_local")),
            version=version,
        ).validate()
        if row.stadium_id in stadiums:
            raise NFLContextError(f"duplicate stadium_id:{row.stadium_id}")
        stadiums[row.stadium_id] = row
        for team_id in row.team_ids:
            if team_id in team_to_stadium:
                raise NFLContextError(f"duplicate team stadium mapping:{team_id}")
            team_to_stadium[team_id] = row.stadium_id

    return {
        "version": version,
        "registry_path": str(registry_path),
        "registry_sha256": sha256(raw).hexdigest(),
        "stadiums": stadiums,
        "team_to_stadium": team_to_stadium,
    }


def stadium_registry_manifest(registry: Mapping[str, Any]) -> dict[str, Any]:
    stadiums = registry.get("stadiums") or {}
    return {
        "schema_version": 1,
        "sport": "NFL",
        "source_name": "SPORTSEDGE_NFL_STADIUM_REGISTRY",
        "version": str(registry.get("version") or ""),
        "source_sha256": str(registry.get("registry_sha256") or ""),
        "stadium_count": len(stadiums),
        "team_count": len(registry.get("team_to_stadium") or {}),
        "stadiums": {key: asdict(value) for key, value in sorted(stadiums.items())},
    }
