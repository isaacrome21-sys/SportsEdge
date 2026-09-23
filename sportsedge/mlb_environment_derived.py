"""Derived MLB pregame environment context from public NWS grid data.

This module standardizes physical weather quantities and computes moist-air density
from actual NWS surface pressure, temperature, and relative humidity. It deliberately
does not infer park factors, roof state, stadium-relative wind components, or delay
risk. Those require separate evidence/geometry and remain fail-closed.

The output is research/context only and never creates Model_P.
"""
from __future__ import annotations

import math
from typing import Any, Mapping

SOURCE = "NWS_GRID_DERIVED_MLB_ENVIRONMENT"
SCHEMA_VERSION = "mlb_environment_derived_v1"


class MLBEnvironmentDerivedError(ValueError):
    pass


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _grid_measure(grid: Mapping[str, Any], key: str) -> tuple[float | None, str | None]:
    row = grid.get(key)
    if not isinstance(row, Mapping):
        return None, None
    return _number(row.get("value")), str(row.get("unit_code") or "").strip() or None


def _temperature_c(value: float | None, unit: str | None) -> float | None:
    if value is None:
        return None
    text = str(unit or "")
    if "degC" in text:
        return value
    if "degF" in text:
        return (value - 32.0) * 5.0 / 9.0
    return None


def _pressure_pa(value: float | None, unit: str | None) -> float | None:
    if value is None:
        return None
    text = str(unit or "")
    if text.endswith(":Pa") or text == "Pa" or "wmoUnit:Pa" in text:
        return value
    if "hPa" in text:
        return value * 100.0
    return None


def _humidity_pct(value: float | None, unit: str | None) -> float | None:
    if value is None:
        return None
    text = str(unit or "")
    if "percent" not in text and text not in {"%", "pct"}:
        return None
    if not 0.0 <= value <= 100.0:
        return None
    return value


def _wind_speed_mph(value: float | None, unit: str | None) -> float | None:
    if value is None:
        return None
    text = str(unit or "")
    if "km_h" in text or "km/h" in text:
        return value * 0.621371192237334
    if "m_s" in text or "m/s" in text:
        return value * 2.2369362920544
    if "mi_h" in text or "mph" in text:
        return value
    return None


def _direction_degrees(value: float | None, unit: str | None) -> float | None:
    if value is None:
        return None
    text = str(unit or "")
    if "degree" not in text and text not in {"deg", "degrees"}:
        return None
    return value % 360.0


def saturation_vapor_pressure_pa(temperature_c: float) -> float:
    """Buck equation saturation vapor pressure over liquid water in pascals."""
    t = float(temperature_c)
    return 611.21 * math.exp((18.678 - t / 234.5) * (t / (257.14 + t)))


def moist_air_density_kg_m3(
    *,
    temperature_c: float,
    relative_humidity_pct: float,
    surface_pressure_pa: float,
) -> float:
    """Compute moist-air density from temperature, RH, and actual pressure."""
    t_c = float(temperature_c)
    rh = float(relative_humidity_pct)
    pressure = float(surface_pressure_pa)
    if not -90.0 < t_c < 70.0:
        raise MLBEnvironmentDerivedError("TEMPERATURE_OUT_OF_RANGE")
    if not 0.0 <= rh <= 100.0:
        raise MLBEnvironmentDerivedError("HUMIDITY_OUT_OF_RANGE")
    if not 50_000.0 < pressure < 120_000.0:
        raise MLBEnvironmentDerivedError("PRESSURE_OUT_OF_RANGE")

    kelvin = t_c + 273.15
    vapor_pressure = (rh / 100.0) * saturation_vapor_pressure_pa(t_c)
    dry_pressure = pressure - vapor_pressure
    if dry_pressure <= 0.0:
        raise MLBEnvironmentDerivedError("INVALID_DRY_AIR_PRESSURE")
    rho = dry_pressure / (287.058 * kelvin) + vapor_pressure / (461.495 * kelvin)
    if not math.isfinite(rho) or rho <= 0.0:
        raise MLBEnvironmentDerivedError("INVALID_AIR_DENSITY")
    return rho


def derive_environment_context(weather_roof: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(weather_roof, Mapping):
        raise MLBEnvironmentDerivedError("WEATHER_ROOF_MUST_BE_OBJECT")
    grid = weather_roof.get("grid") or {}
    if not isinstance(grid, Mapping):
        grid = {}

    temp_raw, temp_unit = _grid_measure(grid, "temperature")
    humidity_raw, humidity_unit = _grid_measure(grid, "relativeHumidity")
    pressure_raw, pressure_unit = _grid_measure(grid, "surfacePressure")
    wind_raw, wind_unit = _grid_measure(grid, "windSpeed")
    direction_raw, direction_unit = _grid_measure(grid, "windDirection")
    precip_raw, precip_unit = _grid_measure(grid, "probabilityOfPrecipitation")
    dewpoint_raw, dewpoint_unit = _grid_measure(grid, "dewpoint")

    temperature_c = _temperature_c(temp_raw, temp_unit)
    humidity_pct = _humidity_pct(humidity_raw, humidity_unit)
    pressure_pa = _pressure_pa(pressure_raw, pressure_unit)
    wind_speed_mph = _wind_speed_mph(wind_raw, wind_unit)
    wind_direction_degrees = _direction_degrees(direction_raw, direction_unit)
    precip_probability_pct = _humidity_pct(precip_raw, precip_unit)
    dewpoint_c = _temperature_c(dewpoint_raw, dewpoint_unit)

    blockers: list[str] = []
    for name, value in (
        ("temperature_c", temperature_c),
        ("relative_humidity_pct", humidity_pct),
        ("surface_pressure_pa", pressure_pa),
    ):
        if value is None:
            blockers.append(name)

    air_density = None
    if not blockers:
        assert temperature_c is not None and humidity_pct is not None and pressure_pa is not None
        air_density = moist_air_density_kg_m3(
            temperature_c=temperature_c,
            relative_humidity_pct=humidity_pct,
            surface_pressure_pa=pressure_pa,
        )

    values = {
        "temperature_c": None if temperature_c is None else round(temperature_c, 6),
        "temperature_f": None if temperature_c is None else round(temperature_c * 9.0 / 5.0 + 32.0, 6),
        "relative_humidity_pct": None if humidity_pct is None else round(humidity_pct, 6),
        "dewpoint_c": None if dewpoint_c is None else round(dewpoint_c, 6),
        "surface_pressure_pa": None if pressure_pa is None else round(pressure_pa, 6),
        "air_density_kg_m3": None if air_density is None else round(air_density, 8),
        "wind_speed_mph": None if wind_speed_mph is None else round(wind_speed_mph, 6),
        "wind_direction_degrees": None if wind_direction_degrees is None else round(wind_direction_degrees, 6),
        "precip_probability_pct": None if precip_probability_pct is None else round(precip_probability_pct, 6),
        "roof_state": weather_roof.get("roof_state"),
        "roof_type": weather_roof.get("roof_type"),
        # Stadium-relative components need outfield bearing/orientation and are not guessed.
        "wind_out_component_mph": None,
        "wind_in_component_mph": None,
        "delay_risk": None,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "source": SOURCE,
        "game_pk": weather_roof.get("game_pk"),
        "as_of_utc": weather_roof.get("as_of_utc"),
        "scheduled_start_utc": weather_roof.get("scheduled_start_utc"),
        "status": "AVAILABLE" if not blockers else "INCOMPLETE",
        "required_input_blockers": blockers,
        "values": values,
        "source_weather_sha256": weather_roof.get("payload_sha256"),
        "model_p_eligible": False,
        "promotion_status": "RESEARCH_ONLY_UNTIL_TEMPORAL_VALIDATION",
        "policy_notes": (
            "air density uses actual NWS surface pressure; no standard-pressure substitution",
            "stadium-relative wind components require separately governed field orientation",
            "roof state and delay risk remain fail-closed when unproven",
        ),
    }
