"""Price-blind MLB pregame context feature bridge.

Converts the acquired public pregame bundle into deterministic model features.
Sportsbook quotes are never read into this feature vector.
"""
from __future__ import annotations

from hashlib import sha256
import json
from typing import Any, Mapping

from .mlb_context_eligibility import context_eligibility

SCHEMA_VERSION = "mlb_context_model_features_v1"
PUBLIC_LANES = (
    "starters",
    "lineups",
    "injuries_scratches",
    "umpire",
    "statcast",
    "park_venue",
    "weather_roof",
    "bullpen_workload",
)


class MLBContextFeatureError(RuntimeError):
    pass


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _number(obj: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = obj.get(key)
        if isinstance(value, Mapping):
            value = value.get("value")
        if isinstance(value, bool):
            continue
        try:
            if value is not None:
                return float(value)
        except (TypeError, ValueError):
            pass
    return None


def _digest(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return sha256(raw).hexdigest()


def context_model_features(bundle: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(bundle, Mapping):
        raise MLBContextFeatureError("context bundle must be a mapping")
    bad = {"dk_quotes", "sportsbook", "market"}.intersection(bundle)
    if bad:
        raise MLBContextFeatureError(
            "sportsbook price lane present in model input: " + ",".join(sorted(bad))
        )

    starters = _mapping(bundle.get("starters"))
    lineups = _mapping(bundle.get("lineups"))
    injuries = _mapping(bundle.get("injuries_scratches"))
    umpire = _mapping(bundle.get("umpire"))
    statcast = _mapping(bundle.get("statcast"))
    park = _mapping(bundle.get("park_venue"))
    weather = _mapping(bundle.get("weather_roof"))
    bullpen = _mapping(bundle.get("bullpen_workload"))

    complete = _mapping(lineups.get("complete_by_side"))
    probable = _mapping(starters.get("probable_pitchers"))
    away_starter = _mapping(probable.get("away"))
    home_starter = _mapping(probable.get("home"))
    teams = _mapping(bullpen.get("teams"))
    away_bp = _mapping(teams.get("away"))
    home_bp = _mapping(teams.get("home"))

    features = {
        "away_starter_id": away_starter.get("player_id"),
        "home_starter_id": home_starter.get("player_id"),
        "away_lineup_confirmed": bool(complete.get("away")),
        "home_lineup_confirmed": bool(complete.get("home")),
        "umpire_sample_games": _number(umpire, "home_plate_games", "sample_games"),
        "temperature_f": _number(weather, "temperature", "temperature_f"),
        "wind_mph": _number(weather, "wind_speed", "wind_mph"),
        "precip_probability_pct": _number(weather, "precip_probability_pct"),
        "roof_state": weather.get("roof_state"),
        "venue_id": park.get("venue_id"),
        "roof_type": park.get("roof_type"),
        "turf_type": park.get("turf_type"),
        "statcast_bound_pitchers": _number(statcast, "bound_pitcher_count"),
        "statcast_bound_hitters": _number(statcast, "bound_hitter_count"),
        "away_bullpen_pitches_24h": _number(away_bp, "bullpen_pitches_24h"),
        "away_bullpen_pitches_48h": _number(away_bp, "bullpen_pitches_48h"),
        "home_bullpen_pitches_24h": _number(home_bp, "bullpen_pitches_24h"),
        "home_bullpen_pitches_48h": _number(home_bp, "bullpen_pitches_48h"),
        "injury_lane_status": injuries.get("status"),
    }

    eligibility = context_eligibility(bundle)
    gated = dict(features)
    if not eligibility["lanes"]["lineups"]:
        gated["away_lineup_confirmed"] = None
        gated["home_lineup_confirmed"] = None
    if not eligibility["lanes"]["umpire"]:
        gated["umpire_sample_games"] = None
    if not eligibility["lanes"]["weather"]:
        gated["temperature_f"] = None
        gated["wind_mph"] = None
        gated["precip_probability_pct"] = None
    if not eligibility["lanes"]["bullpen_full_game"]:
        for key in (
            "away_bullpen_pitches_24h",
            "away_bullpen_pitches_48h",
            "home_bullpen_pitches_24h",
            "home_bullpen_pitches_48h",
        ):
            gated[key] = None

    public_source = {
        "game_pk": bundle.get("game_pk"),
        "as_of_utc": bundle.get("as_of_utc"),
        "lanes": {lane: bundle.get(lane) for lane in PUBLIC_LANES},
    }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "game_pk": bundle.get("game_pk"),
        "as_of_utc": bundle.get("as_of_utc"),
        "source_public_payload_sha256": _digest(public_source),
        "price_blind": True,
        "lane_status": {
            lane: _mapping(bundle.get(lane)).get("status", "MISSING")
            for lane in PUBLIC_LANES
        },
        "features": gated,
        "eligibility": eligibility,
    }
    payload["feature_sha256"] = _digest(payload)
    return payload


def attach_context_features(
    feature_row: Mapping[str, Any], bundle: Mapping[str, Any]
) -> dict[str, Any]:
    row = dict(feature_row)
    context = context_model_features(bundle)
    row["pregame_context"] = context["features"]
    row["pregame_context_version"] = SCHEMA_VERSION
    row["pregame_context_sha256"] = context["feature_sha256"]
    row["pregame_context_price_blind"] = True
    return row
