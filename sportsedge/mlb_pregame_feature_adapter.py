"""Fail-closed adapter from MLB pregame acquisition into model feature context.

The acquisition bundle contains useful public context and optional caller-supplied
DraftKings quotes. This module standardizes only price-independent context. It does
not create Model_P, estimate coefficients, or treat an acquired field as a validated
predictive feature merely because it exists.

The canonical scored-input readiness map is mutated only when the caller explicitly
requests enforcement and already supplies a complete readiness map for the other
feature families. This prevents a partial adapter from silently declaring unrelated
families ready or globally blocking legacy engines that do not yet emit readiness.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
from typing import Any, Mapping

SCHEMA_VERSION = "mlb_pregame_feature_adapter_v1"
SOURCE = "MLB_PREGAME_PRICE_INDEPENDENT_ADAPTER"

ENVIRONMENT_FIELDS = (
    "park_hr_factor",
    "park_hr_factor_lhb",
    "park_hr_factor_rhb",
    "park_runs_factor",
    "park_1b_factor",
    "park_2b_3b_factor",
    "temperature",
    "wind_speed",
    "wind_direction",
    "wind_out_component",
    "wind_in_component",
    "humidity",
    "air_density",
    "precip_probability",
    "delay_risk",
    "roof_state",
    "dome_state",
)
UMPIRE_FIELDS = (
    "plate_umpire_id",
    "called_strike_tendency",
    "walk_tendency",
    "run_environment_tendency",
)


class MLBPregameFeatureAdapterError(ValueError):
    pass


def _content_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _wind_mph(value: Any) -> float | None:
    number = _number(value)
    if number is not None:
        return number
    match = re.search(r"[-+]?\d+(?:\.\d+)?", str(value or ""))
    return float(match.group(0)) if match else None


def _known(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip()) and value.strip().upper() not in {
            "UNKNOWN", "MISSING", "UNAVAILABLE", "NOT_EVALUABLE",
        }
    return True


def _environment(bundle: Mapping[str, Any]) -> dict[str, Any]:
    park_lane = bundle.get("park_venue") or {}
    weather_lane = bundle.get("weather_roof") or {}
    venue = park_lane.get("venue") if isinstance(park_lane, Mapping) else {}
    forecast = weather_lane.get("forecast") if isinstance(weather_lane, Mapping) else {}
    venue = venue if isinstance(venue, Mapping) else {}
    forecast = forecast if isinstance(forecast, Mapping) else {}

    # Park geometry is context, not a substitute for fitted park factors.
    values = {
        "park_hr_factor": None,
        "park_hr_factor_lhb": None,
        "park_hr_factor_rhb": None,
        "park_runs_factor": None,
        "park_1b_factor": None,
        "park_2b_3b_factor": None,
        "temperature": _number(forecast.get("temperature")),
        "wind_speed": _wind_mph(forecast.get("wind_speed")),
        "wind_direction": forecast.get("wind_direction"),
        "wind_out_component": None,
        "wind_in_component": None,
        "humidity": None,
        "air_density": None,
        "precip_probability": _number(forecast.get("precip_probability_pct")),
        "delay_risk": None,
        "roof_state": weather_lane.get("roof_state") if isinstance(weather_lane, Mapping) else None,
        "dome_state": None,
    }
    missing = tuple(name for name in ENVIRONMENT_FIELDS if not _known(values.get(name)))
    return {
        "values": values,
        "ready": not missing,
        "missing_fields": missing,
        "venue_context": {
            "venue_id": venue.get("venue_id"),
            "venue_name": venue.get("venue_name"),
            "roof_type": venue.get("roof_type"),
            "turf_type": venue.get("turf_type"),
            "latitude": venue.get("latitude"),
            "longitude": venue.get("longitude"),
            "field_dimensions": venue.get("field_dimensions"),
        },
        "policy_notes": (
            "static venue geometry is not a fitted park factor",
            "roof_state UNKNOWN is never promoted to an open/closed assumption",
            "wind vector, humidity, air density, and delay risk must be derived before environment can be ready",
        ),
    }


def _umpire(bundle: Mapping[str, Any]) -> dict[str, Any]:
    lane = bundle.get("umpire") or {}
    zone_lane = bundle.get("umpire_zone") or {}
    assignment = lane.get("assignment") if isinstance(lane, Mapping) else {}
    tendencies = lane.get("tendencies") if isinstance(lane, Mapping) else {}
    assignment = assignment if isinstance(assignment, Mapping) else {}
    tendencies = tendencies if isinstance(tendencies, Mapping) else {}
    zone_lane = zone_lane if isinstance(zone_lane, Mapping) else {}
    deltas = tendencies.get("deltas") if isinstance(tendencies, Mapping) else {}
    deltas = deltas if isinstance(deltas, Mapping) else {}

    # Only a sample-passing, PIT-built zone lane may populate the called-strike
    # field. The broader game-level strikeout delta remains context only.
    zone_called_strike = None
    if str(zone_lane.get("status") or "").upper() == "AVAILABLE":
        zone_called_strike = _number(zone_lane.get("called_strike_tendency"))

    values = {
        "plate_umpire_id": assignment.get("umpire_id"),
        "called_strike_tendency": zone_called_strike,
        # Game walk totals are retained below as broad context but are not promoted
        # to the required plate-umpire walk tendency field without PA-level modeling.
        "walk_tendency": None,
        "run_environment_tendency": _number(deltas.get("runs_delta")),
    }
    missing = tuple(name for name in UMPIRE_FIELDS if not _known(values.get(name)))
    return {
        "values": values,
        "ready": not missing,
        "missing_fields": missing,
        "zone_context": {
            "status": zone_lane.get("status"),
            "model_version": zone_lane.get("model_version"),
            "umpire_called_pitches": zone_lane.get("umpire_called_pitches"),
            "raw_called_strike_bias": zone_lane.get("raw_called_strike_bias"),
            "shrunk_called_strike_bias": zone_lane.get("shrunk_called_strike_bias"),
            "source_subset_sha256": zone_lane.get("source_subset_sha256"),
        },
        "broad_game_context": {
            "runs_delta": _number(deltas.get("runs_delta")),
            "strikeouts_delta": _number(deltas.get("strikeouts_delta")),
            "walks_delta": _number(deltas.get("walks_delta")),
            "sample_gate": tendencies.get("sample_gate"),
            "home_plate_games": tendencies.get("home_plate_games"),
        },
        "policy_notes": (
            "game strikeouts_delta is not called_strike_tendency",
            "called_strike_tendency is accepted only from a sample-passing PIT zone residual lane",
            "walks_delta is broad game context and is not substituted for the required walk_tendency field",
        ),
    }


def adapt_pregame_bundle(bundle: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(bundle, Mapping):
        raise MLBPregameFeatureAdapterError("PREGAME_BUNDLE_MUST_BE_OBJECT")
    try:
        game_pk = int(bundle.get("game_pk"))
    except (TypeError, ValueError) as exc:
        raise MLBPregameFeatureAdapterError("PREGAME_GAME_PK_REQUIRED") from exc

    environment = _environment(bundle)
    umpire = _umpire(bundle)
    statcast = bundle.get("statcast") or {}
    starters = bundle.get("starters") or {}
    lineups = bundle.get("lineups") or {}
    park = bundle.get("park_venue") or {}

    output = {
        "schema_version": SCHEMA_VERSION,
        "source": SOURCE,
        "game_pk": game_pk,
        "as_of_utc": bundle.get("as_of_utc"),
        "official_date": bundle.get("official_date"),
        "predictive_context": {
            "starters": deepcopy(starters) if isinstance(starters, Mapping) else {},
            "lineups": deepcopy(lineups) if isinstance(lineups, Mapping) else {},
            "statcast": deepcopy(statcast) if isinstance(statcast, Mapping) else {},
            "park_venue": deepcopy(park) if isinstance(park, Mapping) else {},
            "environment": environment["values"],
            "umpire_context": umpire["values"],
        },
        "family_evaluation": {
            "environment": environment,
            "umpire_context": umpire,
        },
        "feature_family_readiness": {
            "environment": bool(environment["ready"]),
            "umpire_context": bool(umpire["ready"]),
        },
        "excluded_from_predictive_context": ["hybrid_dk"],
        "market_price_data_present": bool((bundle.get("hybrid_dk") or {}).get("quotes"))
        if isinstance(bundle.get("hybrid_dk") or {}, Mapping) else False,
        "model_p_eligible": False,
        "promotion_status": "CONTEXT_ONLY_UNTIL_FITTED_AND_VALIDATED",
    }
    output["payload_sha256"] = _content_sha(output)
    return output


def attach_pregame_context(
    feature_row: Mapping[str, Any],
    bundle: Mapping[str, Any],
    *,
    enforce_family_readiness: bool = False,
) -> dict[str, Any]:
    """Attach standardized context without silently promoting it.

    With enforcement disabled (default), the existing scored-input readiness map is
    untouched. With enforcement enabled, the row must already contain an explicit
    readiness map for its existing model families; this adapter then overwrites only
    the environment and umpire_context entries that it owns.
    """
    if not isinstance(feature_row, Mapping):
        raise MLBPregameFeatureAdapterError("FEATURE_ROW_MUST_BE_OBJECT")
    adapted = adapt_pregame_bundle(bundle)
    row = deepcopy(dict(feature_row))
    if str(row.get("game_pk") or row.get("game_id") or "") != str(adapted["game_pk"]):
        raise MLBPregameFeatureAdapterError("FEATURE_ROW_GAME_ID_MISMATCH")

    row["pregame_context"] = adapted["predictive_context"]
    row["pregame_context_sha256"] = adapted["payload_sha256"]
    row["pregame_context_status"] = adapted["promotion_status"]

    if enforce_family_readiness:
        existing = row.get("feature_family_readiness")
        if not isinstance(existing, Mapping):
            raise MLBPregameFeatureAdapterError("BASE_FEATURE_FAMILY_READINESS_REQUIRED")
        merged = dict(existing)
        merged.update(adapted["feature_family_readiness"])
        row["feature_family_readiness"] = merged
    return row
