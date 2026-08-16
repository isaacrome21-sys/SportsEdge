from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable, Mapping

from .source_lineage import canonical_json_sha256
from .v7_baseball_features import assert_no_market_contamination, build_v7_baseball_features
from .v7_environment_context import build_v7_environment_context

V7_COMBINED_FEATURE_CONTRACT_VERSION = "mlb_v7_combined_feature_contract_v1"

V7_MODEL_FEATURE_PATHS = (
    "baseball.starter.days_rest",
    "baseball.starter.pitches_7d",
    "baseball.starter.pitches_14d",
    "baseball.starter.starts_30d",
    "baseball.starter.avg_pitches_5starts",
    "baseball.bullpen.relief_pitches_1d",
    "baseball.bullpen.relief_pitches_3d",
    "baseball.bullpen.relief_pitches_7d",
    "baseball.bullpen.relievers_used_1d",
    "baseball.bullpen.relievers_back_to_back",
    "baseball.statcast.pa_7d",
    "baseball.statcast.pa_14d",
    "baseball.statcast.pa_30d",
    "baseball.statcast.pa_75d",
    "baseball.statcast.xwoba_14d",
    "baseball.statcast.xwoba_30d",
    "baseball.statcast.hard_hit_30d",
    "baseball.statcast.barrel_30d",
    "baseball.statcast.whiff_30d",
    "baseball.platoon.same_side",
    "baseball.platoon.batter_xwoba_vs_hand",
    "baseball.platoon.pitcher_xwoba_allowed_vs_hand",
    "context.park.run_factor",
    "context.park.hr_factor_lhb",
    "context.park.hr_factor_rhb",
    "context.weather.temperature_f",
    "context.weather.humidity_pct",
    "context.weather.pressure_hpa",
    "context.weather.wind_mph",
    "context.weather.wind_out_to_center_mph",
    "context.weather.precip_probability",
    "context.weather.roof_closed",
    "context.travel.travel_km",
    "context.travel.timezone_shift_hours",
    "context.travel.days_rest",
    "context.travel.consecutive_game_days",
    "context.travel.doubleheader",
    "context.umpire.assignment_known",
    "context.umpire.called_strike_delta",
    "context.umpire.bb_rate_delta",
    "context.umpire.run_rate_delta",
    "context.umpire.prior_pitches",
    "context.catcher.catcher_known",
    "context.catcher.framing_runs_per_1000",
    "context.catcher.strike_rate_delta",
    "context.catcher.prior_called_pitches",
)

V7_COMBINED_FEATURE_CONTRACT_SHA256 = canonical_json_sha256({
    "feature_contract_version": V7_COMBINED_FEATURE_CONTRACT_VERSION,
    "model_feature_paths": list(V7_MODEL_FEATURE_PATHS),
})


class V7FeatureBundleError(ValueError):
    pass


def _strip_dynamic_component_hash(component: Mapping[str, Any]) -> dict[str, Any]:
    out = deepcopy(dict(component))
    dynamic_hash = out.pop("feature_contract_sha256", None)
    if dynamic_hash is not None:
        out["component_payload_sha256"] = str(dynamic_hash)
    return out


def get_numeric_path(payload: Mapping[str, Any], path: str) -> float:
    value: Any = payload
    for part in str(path).split("."):
        if not isinstance(value, Mapping) or part not in value:
            raise V7FeatureBundleError(f"missing feature path: {path}")
        value = value[part]
    if isinstance(value, bool):
        return float(value)
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise V7FeatureBundleError(f"feature path not numeric: {path}") from exc
    return out


def model_vector(payload: Mapping[str, Any], *, feature_paths: Iterable[str] = V7_MODEL_FEATURE_PATHS) -> dict[str, float]:
    if str(payload.get("feature_contract_sha256") or "") != V7_COMBINED_FEATURE_CONTRACT_SHA256:
        raise V7FeatureBundleError("combined feature contract hash mismatch")
    assert_no_market_contamination(payload)
    return {path: get_numeric_path(payload, path) for path in feature_paths}


def build_v7_feature_payload(
    *,
    as_of: Any,
    starter_rows: Iterable[Mapping[str, Any]],
    bullpen_rows: Iterable[Mapping[str, Any]],
    statcast_rows: Iterable[Mapping[str, Any]],
    platoon: Mapping[str, Any],
    park: Mapping[str, Any],
    weather: Mapping[str, Any],
    travel: Mapping[str, Any],
    umpire: Mapping[str, Any] | None,
    catcher: Mapping[str, Any] | None,
) -> dict[str, Any]:
    baseball = build_v7_baseball_features(
        as_of=as_of,
        starter_rows=starter_rows,
        bullpen_rows=bullpen_rows,
        statcast_rows=statcast_rows,
        platoon=platoon,
    )
    context = build_v7_environment_context(
        as_of=as_of,
        park=park,
        weather=weather,
        travel=travel,
        umpire=umpire,
        catcher=catcher,
    )
    payload = {
        "feature_contract_version": V7_COMBINED_FEATURE_CONTRACT_VERSION,
        "feature_contract_sha256": V7_COMBINED_FEATURE_CONTRACT_SHA256,
        "feature_as_of_utc": baseball["feature_as_of_utc"],
        "baseball": _strip_dynamic_component_hash(baseball),
        "context": _strip_dynamic_component_hash(context),
    }
    assert_no_market_contamination(payload)
    model_vector(payload)
    payload["feature_payload_sha256"] = canonical_json_sha256(payload)
    return payload
