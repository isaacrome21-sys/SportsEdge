from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from .runtime import parse_timestamp
from .source_lineage import canonical_json_sha256
from .v7_sources import (
    fetch_mlb_live_feed,
    fetch_nws_hourly,
    extract_home_plate_umpire,
    extract_starting_catcher_ids,
    source_manifest,
)

MLB_HYBRID_CONTEXT_SCHEMA_VERSION = "mlb_hybrid_context_autopull_v1"

CONTEXT_CLASSES = (
    "park",
    "weather",
    "bullpen",
    "umpire",
    "defense",
    "catcher_framing",
    "platoon",
    "workload",
)

PROHIBITED_CONTEXT_CLASSES = frozenset({
    "social_pick",
    "handicapper_pick",
    "public_betting",
    "market_split",
    "sportsbook_price",
    "market_probability",
})


class MLBContextAutopullError(ValueError):
    pass


@dataclass(frozen=True)
class ContextObservation:
    context_class: str
    status: str
    source: str
    observed_at_utc: str
    payload: Any
    model_p_eligible: bool = False
    lane: str = "HYBRID_CONTEXT"


def _utc(value: Any, field: str) -> datetime:
    try:
        dt = value if isinstance(value, datetime) else parse_timestamp(value)
    except Exception as exc:
        raise MLBContextAutopullError(f"invalid {field}") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise MLBContextAutopullError(f"{field} must be timezone-aware")
    return dt.astimezone(timezone.utc)


def _venue_coordinates(live_feed: Mapping[str, Any]) -> tuple[float, float] | None:
    venue = ((live_feed.get("gameData") or {}).get("venue") or {})
    location = venue.get("location") or {}
    coords = location.get("defaultCoordinates") or {}
    try:
        lat = float(coords["latitude"])
        lon = float(coords["longitude"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


def _observation(*, context_class: str, source: str, observed_at: datetime, payload: Any, status: str = "AVAILABLE") -> ContextObservation:
    key = str(context_class).strip().lower()
    if key in PROHIBITED_CONTEXT_CLASSES:
        raise MLBContextAutopullError(f"prohibited hybrid context class: {key}")
    if key not in CONTEXT_CLASSES:
        raise MLBContextAutopullError(f"unknown hybrid context class: {key}")
    return ContextObservation(
        context_class=key,
        status=str(status),
        source=str(source),
        observed_at_utc=observed_at.isoformat(),
        payload=payload,
    )


def build_autopull_plan() -> dict[str, dict[str, Any]]:
    """Describe the fail-closed source strategy for Carty-style MLB context.

    Social/public-betting feeds are intentionally absent. This lane is for
    baseball/environment context only and is never a Truth Gate input by itself.
    """
    return {
        "park": {"primary": "SPORTSEDGE_PIT_PARK_FACTORS", "auto_pull": True, "fallback": None},
        "weather": {"primary": "NWS_HOURLY", "auto_pull": True, "fallback": None},
        "bullpen": {"primary": "MLB_STATSAPI_GAME_LOGS", "auto_pull": True, "fallback": None},
        "umpire": {"primary": "MLB_STATSAPI_ASSIGNMENT+PIT_UMPIRE_HISTORY", "auto_pull": True, "fallback": None},
        "defense": {"primary": "PIT_STATCAST_DEFENSE", "auto_pull": True, "fallback": "MLB_STATSAPI_FIELDING"},
        "catcher_framing": {"primary": "MLB_STATSAPI_STARTER+PIT_FRAMING_HISTORY", "auto_pull": True, "fallback": None},
        "platoon": {"primary": "PIT_STATCAST_PLATOON", "auto_pull": True, "fallback": None},
        "workload": {"primary": "MLB_STATSAPI_GAME_LOGS", "auto_pull": True, "fallback": None},
    }


def collect_mlb_hybrid_context(
    *,
    game_pk: int,
    as_of: Any,
    providers: Mapping[str, Callable[[int, datetime, Mapping[str, Any]], Any]] | None = None,
    opener: Callable | None = None,
) -> dict[str, Any]:
    """Collect a provenance-preserving MLB context sidecar.

    Core current-game identity, umpire/catcher assignments and weather are pulled
    from public MLB/NWS sources. Historical/PIT transforms (park, bullpen,
    defense, framing, platoon and workload) are supplied through named providers.
    Missing providers remain explicit MISSING rows; no values are inferred.
    """
    asof = _utc(as_of, "as_of")
    kwargs = {} if opener is None else {"opener": opener}
    live = fetch_mlb_live_feed(int(game_pk), retrieved_at=asof, **kwargs)
    live_payload = live.payload if isinstance(live.payload, Mapping) else {}

    observations: dict[str, ContextObservation] = {}
    umpire = extract_home_plate_umpire(live_payload)
    observations["umpire"] = _observation(
        context_class="umpire",
        source="MLB_STATSAPI_ASSIGNMENT",
        observed_at=asof,
        payload=umpire,
        status="AVAILABLE" if umpire else "MISSING",
    )
    catchers = extract_starting_catcher_ids(live_payload)
    observations["catcher_framing"] = _observation(
        context_class="catcher_framing",
        source="MLB_STATSAPI_STARTING_CATCHER",
        observed_at=asof,
        payload=catchers,
        status="AVAILABLE" if any(catchers.values()) else "MISSING",
    )

    weather_manifests: list[dict[str, Any]] = []
    coords = _venue_coordinates(live_payload)
    if coords is None:
        observations["weather"] = _observation(
            context_class="weather", source="NWS_HOURLY", observed_at=asof,
            payload=None, status="MISSING_VENUE_COORDINATES",
        )
    else:
        point, forecast = fetch_nws_hourly(coords[0], coords[1], retrieved_at=asof, **kwargs)
        weather_manifests = [source_manifest(point), source_manifest(forecast)]
        observations["weather"] = _observation(
            context_class="weather", source="NWS_HOURLY", observed_at=asof,
            payload=forecast.payload, status="AVAILABLE",
        )

    provider_map = dict(providers or {})
    for context_class in CONTEXT_CLASSES:
        if context_class in observations:
            continue
        provider = provider_map.get(context_class)
        if provider is None:
            observations[context_class] = _observation(
                context_class=context_class,
                source=build_autopull_plan()[context_class]["primary"],
                observed_at=asof,
                payload=None,
                status="MISSING_PROVIDER",
            )
            continue
        try:
            payload = provider(int(game_pk), asof, live_payload)
        except Exception as exc:
            raise MLBContextAutopullError(f"{context_class} provider failed") from exc
        observations[context_class] = _observation(
            context_class=context_class,
            source=build_autopull_plan()[context_class]["primary"],
            observed_at=asof,
            payload=payload,
            status="AVAILABLE" if payload is not None else "MISSING",
        )

    payload = {
        "schema_version": MLB_HYBRID_CONTEXT_SCHEMA_VERSION,
        "game_pk": int(game_pk),
        "as_of_utc": asof.isoformat(),
        "lane": "HYBRID_CONTEXT",
        "truth_gate_eligible": False,
        "model_p_eligible": False,
        "source_manifests": [source_manifest(live), *weather_manifests],
        "observations": {k: asdict(v) for k, v in observations.items()},
    }
    payload["payload_sha256"] = canonical_json_sha256(payload)
    return payload


def missing_context_classes(bundle: Mapping[str, Any]) -> tuple[str, ...]:
    observations = bundle.get("observations") or {}
    missing = []
    for key in CONTEXT_CLASSES:
        row = observations.get(key) or {}
        if str(row.get("status") or "").upper() != "AVAILABLE":
            missing.append(key)
    return tuple(missing)
