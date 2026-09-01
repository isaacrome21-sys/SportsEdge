from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
from typing import Any, Callable, Mapping
from urllib.request import Request, urlopen

from .context_autopull import NFLContextError
from .context_providers import build_official_injury_provider, build_weather_roof_provider, fetch_nws_hourly_raw
from .stadium_registry import load_stadium_registry

OFFICIAL_INJURY_HOSTS = frozenset({"www.nfl.com", "nfl.com"})


def _host(uri: str) -> str:
    from urllib.parse import urlparse
    return (urlparse(str(uri)).hostname or "").lower()


def assert_official_injury_uri(uri: str) -> str:
    value = str(uri or "").strip()
    if not value.startswith("https://") or _host(value) not in OFFICIAL_INJURY_HOSTS:
        raise NFLContextError("injury source URI not approved official NFL source")
    return value


def fetch_json_bytes(uri: str, *, opener: Callable = urlopen, headers: Mapping[str, str] | None = None) -> tuple[Mapping[str, Any], str]:
    try:
        with opener(Request(uri, headers=dict(headers or {})), timeout=20) as response:
            raw = response.read()
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise NFLContextError(f"source fetch failed:{uri}") from exc
    if not isinstance(payload, Mapping):
        raise NFLContextError("source JSON must be object")
    return payload, sha256(raw).hexdigest()


def weather_roof_auto_adapter(*, game_id: str, stadium_id: str, kickoff: Any, as_of: Any, authoritative_roof: str | None = None, opener: Callable = urlopen) -> Mapping[str, Any]:
    registry = load_stadium_registry()
    stadium = (registry["stadiums"] or {}).get(str(stadium_id))
    if stadium is None:
        raise NFLContextError(f"stadium not found:{stadium_id}")
    hourly, uri, digest = fetch_nws_hourly_raw(lat=stadium.lat, lon=stadium.lon, opener=opener)
    row = dict(build_weather_roof_provider(
        game_id=game_id,
        stadium=stadium,
        kickoff=kickoff,
        as_of=as_of,
        nws_payload=hourly,
        source_uri=uri,
        source_sha256=digest,
        authoritative_roof=authoritative_roof,
    ))
    payload = dict(row.get("payload") or {})
    payload["stadium_registry_sha256"] = registry["registry_sha256"]
    payload["stadium_registry_version"] = registry["version"]
    row["payload"] = payload
    return row


def official_injury_auto_adapter(*, game_id: str, team_id: str, player_id: str, as_of: Any, source_uri: str, source_payload: Mapping[str, Any]) -> Mapping[str, Any]:
    assert_official_injury_uri(source_uri)
    return build_official_injury_provider(
        game_id=game_id,
        team_id=team_id,
        player_id=player_id,
        as_of=as_of,
        source_uri=source_uri,
        source_payload=source_payload,
        official_source=True,
    )
