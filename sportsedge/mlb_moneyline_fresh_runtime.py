"""Fresh runtime hard-check receipt for the governed MLB MONEYLINE transition.

This module is deliberately non-authoritative. It can only attest that the exact
frozen Model_P artifact still executes through the canonical production MONEYLINE
engine against a genuinely fresh, paired DraftKings observation while the live
deployment remains fail closed. It never edits deployments, changes stake, or
emits an OFFICIAL bet.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from math import isfinite
import re
from typing import Any, Mapping

from .devig import devig_with_policy, validate_pair
from .edge_floors import load_edge_floor_config, require_frozen_devig_policy
from .engine_registry import engine_registry
from .mlb_model_artifact import mlb_model_artifact_sha256
from .mlb_moneyline_forward_prediction import (
    PREDICTION_VERSION,
    PRODUCTION_ENGINE_DISPATCH,
    production_moneyline_model_input,
)
from .orchestrator import run_candidate

SCHEMA = "mlb_moneyline_fresh_runtime_hard_checks_v1"
PASS_STATUS = "FRESH_RUNTIME_HARD_CHECKS_PASS"
READINESS_SCHEMA = "mlb_moneyline_transition_readiness_v1"
READINESS_STATUS = "GOVERNANCE_DOCUMENTATION_COMPLETE_FRESH_RUNTIME_STILL_REQUIRED"
SOURCE_CLASS = "DRAFTKINGS_DIRECT_WEB_V1"
SPORT_KEY = "baseball_mlb"
SPORTSBOOK = "draftkings"
MAX_QUOTE_AGE_SECONDS = 60.0


class MLBMoneylineFreshRuntimeError(RuntimeError):
    pass


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _ts(value: Any, field: str) -> datetime:
    try:
        out = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise MLBMoneylineFreshRuntimeError(f"{field}: invalid timestamp") from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise MLBMoneylineFreshRuntimeError(f"{field}: timezone required")
    return out.astimezone(timezone.utc)


def _utc(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise MLBMoneylineFreshRuntimeError(f"{field}: timezone required")
    return value.astimezone(timezone.utc)


def _sha(value: Any, field: str) -> str:
    text = str(value or "").lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise MLBMoneylineFreshRuntimeError(f"{field}: invalid sha256")
    return text


def _norm_team(value: Any) -> str:
    text = re.sub(r"[^a-z0-9 ]+", " ", str(value or "").lower())
    return " ".join(text.split())


def _prob(value: Any, field: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise MLBMoneylineFreshRuntimeError(f"{field}: invalid probability") from exc
    if not isfinite(out) or not 0.0 < out < 1.0:
        raise MLBMoneylineFreshRuntimeError(f"{field}: invalid probability")
    return out


def _require_non_authority(value: Mapping[str, Any], label: str) -> None:
    for field in (
        "promotion_authority",
        "deployment_change_allowed",
        "staking_change_allowed",
        "official_change_allowed",
    ):
        if field in value and value.get(field) is not False:
            raise MLBMoneylineFreshRuntimeError(f"{label} carries forbidden authority: {field}")


def _identity(readiness: Mapping[str, Any]) -> dict[str, str]:
    if readiness.get("schema_version") != READINESS_SCHEMA:
        raise MLBMoneylineFreshRuntimeError("transition readiness schema mismatch")
    if readiness.get("status") != READINESS_STATUS:
        raise MLBMoneylineFreshRuntimeError("governance documentation is not complete")
    if readiness.get("governance_documentation_complete") is not True:
        raise MLBMoneylineFreshRuntimeError("governance documentation flag not complete")
    if readiness.get("fresh_runtime_hard_checks_required") is not True:
        raise MLBMoneylineFreshRuntimeError("fresh runtime requirement missing")
    if readiness.get("state_transition_apply_now") is not False:
        raise MLBMoneylineFreshRuntimeError("readiness receipt attempted state transition")
    _require_non_authority(readiness, "transition readiness")
    identity = {
        "lane_id": str(readiness.get("lane_id") or ""),
        "model_artifact_sha256": _sha(readiness.get("model_artifact_sha256"), "model artifact"),
        "market_definition_sha256": _sha(readiness.get("market_definition_sha256"), "market definition"),
        "policy_id": str(readiness.get("policy_id") or ""),
        "policy_sha256": _sha(readiness.get("policy_sha256"), "policy"),
    }
    if not identity["lane_id"] or not identity["policy_id"]:
        raise MLBMoneylineFreshRuntimeError("transition identity incomplete")
    return identity


def _canonical_quotes(*, prediction: Mapping[str, Any], capture: Mapping[str, Any], observed: datetime) -> tuple[dict[str, Any], dict[str, Any]]:
    moneyline = capture.get("moneyline")
    if not isinstance(moneyline, Mapping) or moneyline.get("status") != "OK":
        raise MLBMoneylineFreshRuntimeError("paired DraftKings MONEYLINE required")
    try:
        home_odds = int(moneyline.get("home_price_american"))
        away_odds = int(moneyline.get("away_price_american"))
    except (TypeError, ValueError) as exc:
        raise MLBMoneylineFreshRuntimeError("paired moneyline odds invalid") from exc
    game_id = str(int(prediction.get("game_pk")))
    common = {
        "game_id": game_id,
        "period": "FG",
        "market": "MONEYLINE",
        "entity_id": game_id,
        "line": 0.0,
        "book_key": SPORTSBOOK,
        "sportsbook": SPORTSBOOK,
        "retrieved_at": observed,
        "ttl_seconds": int(MAX_QUOTE_AGE_SECONDS),
        "is_alternate": False,
        "raw_market_name": "Moneyline",
    }
    return (
        {**common, "side": "HOME", "american_odds": home_odds, "offer_id": f"{capture.get('provider_event_id')}:HOME"},
        {**common, "side": "AWAY", "american_odds": away_odds, "offer_id": f"{capture.get('provider_event_id')}:AWAY"},
    )


def evaluate_fresh_runtime_hard_checks(
    *,
    transition_readiness: Mapping[str, Any],
    prediction: Mapping[str, Any],
    capture: Mapping[str, Any],
    deployments: Mapping[str, Any],
    now: datetime,
    floor_config_path: str = "config/truth_gate_floors.json",
) -> dict[str, Any]:
    identity = _identity(transition_readiness)
    now_utc = _utc(now, "now")

    markets = deployments.get("markets")
    if not isinstance(markets, Mapping):
        raise MLBMoneylineFreshRuntimeError("deployments markets unavailable")
    moneyline_deployment = markets.get("MONEYLINE")
    if not isinstance(moneyline_deployment, Mapping):
        raise MLBMoneylineFreshRuntimeError("MONEYLINE deployment unavailable")
    if moneyline_deployment.get("eligible") is not False:
        raise MLBMoneylineFreshRuntimeError("fresh pre-transition check requires MONEYLINE eligible=false")
    deployment_sha = _canonical_sha256(dict(moneyline_deployment))
    if deployment_sha != str(transition_readiness.get("deployment_snapshot_sha256") or ""):
        raise MLBMoneylineFreshRuntimeError("deployment snapshot drift")

    active_artifact = _sha(mlb_model_artifact_sha256(), "active model artifact")
    if active_artifact != identity["model_artifact_sha256"]:
        raise MLBMoneylineFreshRuntimeError("active model artifact drift")

    if prediction.get("schema_version") != PREDICTION_VERSION:
        raise MLBMoneylineFreshRuntimeError("prediction schema mismatch")
    if prediction.get("promotion_authority") is not False:
        raise MLBMoneylineFreshRuntimeError("prediction carries forbidden authority")
    if prediction.get("market") != "MONEYLINE" or prediction.get("model_side") != "HOME":
        raise MLBMoneylineFreshRuntimeError("prediction market/reference side mismatch")
    if prediction.get("market_blind") is not True:
        raise MLBMoneylineFreshRuntimeError("prediction is not market blind")
    if str(prediction.get("production_engine_dispatch") or "") != PRODUCTION_ENGINE_DISPATCH:
        raise MLBMoneylineFreshRuntimeError("prediction production dispatch mismatch")
    if _sha(prediction.get("model_artifact_sha256"), "prediction model artifact") != active_artifact:
        raise MLBMoneylineFreshRuntimeError("prediction artifact mismatch")
    start = _ts(prediction.get("event_start_ts"), "prediction event_start_ts")
    feature_asof = _ts(prediction.get("feature_asof_ts"), "feature_asof_ts")
    generated = _ts(prediction.get("prediction_generated_at_utc"), "prediction_generated_at_utc")
    if not feature_asof < start or not generated < start:
        raise MLBMoneylineFreshRuntimeError("prediction PIT chronology invalid")

    if capture.get("promotion_authority") is not False:
        raise MLBMoneylineFreshRuntimeError("capture carries forbidden authority")
    if capture.get("source_class") != SOURCE_CLASS or capture.get("sport_key") != SPORT_KEY:
        raise MLBMoneylineFreshRuntimeError("capture source class mismatch")
    if str(capture.get("sportsbook") or "").lower() != SPORTSBOOK:
        raise MLBMoneylineFreshRuntimeError("capture sportsbook mismatch")
    if _sha(capture.get("model_artifact_sha256"), "capture model artifact") != active_artifact:
        raise MLBMoneylineFreshRuntimeError("capture artifact mismatch")
    raw_sha = _sha(capture.get("raw_sha256"), "capture raw payload")
    provider_event_id = str(capture.get("provider_event_id") or "").strip()
    if not provider_event_id:
        raise MLBMoneylineFreshRuntimeError("provider event id missing")
    if _norm_team(capture.get("home_team")) != _norm_team(prediction.get("home_team")):
        raise MLBMoneylineFreshRuntimeError("home team identity mismatch")
    if _norm_team(capture.get("away_team")) != _norm_team(prediction.get("away_team")):
        raise MLBMoneylineFreshRuntimeError("away team identity mismatch")
    capture_start = _ts(capture.get("scheduled_start_utc"), "capture scheduled_start_utc")
    if abs((capture_start - start).total_seconds()) > 1.0:
        raise MLBMoneylineFreshRuntimeError("capture event start identity mismatch")
    observed = _ts(capture.get("observed_at_utc"), "capture observed_at_utc")
    if not observed < start:
        raise MLBMoneylineFreshRuntimeError("capture is not pregame")
    quote_age = (now_utc - observed).total_seconds()
    if quote_age < 0:
        raise MLBMoneylineFreshRuntimeError("capture observation is in the future")
    if quote_age > MAX_QUOTE_AGE_SECONDS:
        raise MLBMoneylineFreshRuntimeError("capture is stale for fresh runtime attestation")

    try:
        game_pk = int(prediction.get("game_pk"))
        away_mean = float(prediction.get("away_mean_runs"))
        home_mean = float(prediction.get("home_mean_runs"))
        simulations = int(prediction.get("mc_paths"))
    except (TypeError, ValueError) as exc:
        raise MLBMoneylineFreshRuntimeError("prediction production inputs invalid") from exc
    model_input_home = production_moneyline_model_input(
        game_pk=game_pk,
        away_mean_runs=away_mean,
        home_mean_runs=home_mean,
        feature_source_hash=str(prediction.get("feature_source_hash") or ""),
        simulations=simulations,
    )
    model_input_away = {**model_input_home, "side": "AWAY"}
    engine = engine_registry()["MONEYLINE"]
    home_output = dict(engine(model_input_home))
    away_output = dict(engine(model_input_away))
    home_p = _prob(home_output.get("model_p"), "runtime home Model_P")
    away_p = _prob(away_output.get("model_p"), "runtime away Model_P")
    frozen_home_p = _prob(prediction.get("model_p"), "frozen home Model_P")
    if abs(home_p - frozen_home_p) > 1e-12:
        raise MLBMoneylineFreshRuntimeError("runtime Model_P drift from frozen prediction")
    if abs((home_p + away_p) - 1.0) > 1e-10:
        raise MLBMoneylineFreshRuntimeError("runtime home/away Model_P do not complement")
    for field in ("model_input_hash", "distribution_sha256", "readout_sha256"):
        if str(home_output.get(field) or "") != str(prediction.get(field) or ""):
            raise MLBMoneylineFreshRuntimeError(f"runtime production parity drift: {field}")

    home_quote, away_quote = _canonical_quotes(
        prediction=prediction, capture=capture, observed=observed
    )
    try:
        validate_pair(home_quote, away_quote)
        devig_policy = require_frozen_devig_policy(config=load_edge_floor_config(floor_config_path))
        home_fair = float(
            devig_with_policy(home_quote, away_quote, policy=devig_policy).fair_probability_for_decision
        )
        away_fair = float(
            devig_with_policy(away_quote, home_quote, policy=devig_policy).fair_probability_for_decision
        )
    except Exception as exc:
        raise MLBMoneylineFreshRuntimeError(f"paired no-vig validation failed: {exc}") from exc
    if abs((home_fair + away_fair) - 1.0) > 1e-10:
        raise MLBMoneylineFreshRuntimeError("paired no-vig probabilities do not complement")

    home_run = run_candidate(
        model_input=model_input_home,
        quote=home_quote,
        paired_quote=away_quote,
        deployment={"market": "MONEYLINE", **dict(moneyline_deployment)},
        engine_fn=engine,
        ingestion_now=now_utc,
        finalization_now=now_utc,
        edge_floor_config_path=floor_config_path,
    )
    away_run = run_candidate(
        model_input=model_input_away,
        quote=away_quote,
        paired_quote=home_quote,
        deployment={"market": "MONEYLINE", **dict(moneyline_deployment)},
        engine_fn=engine,
        ingestion_now=now_utc,
        finalization_now=now_utc,
        edge_floor_config_path=floor_config_path,
    )
    for side, run in (("HOME", home_run), ("AWAY", away_run)):
        if run.bet_status != "MODEL_CANDIDATE" or run.model_p is None:
            raise MLBMoneylineFreshRuntimeError(
                f"production pre-transition runtime did not retain {side} Model_P: {run.reason}"
            )
        if not str(run.reason).startswith("OFFICIAL_BLOCKED:"):
            raise MLBMoneylineFreshRuntimeError("production deployment fail-closed reason missing")
        if run.sportsbook != SPORTSBOOK or run.book_key != SPORTSBOOK:
            raise MLBMoneylineFreshRuntimeError("runtime sportsbook identity mismatch")

    return {
        "schema_version": SCHEMA,
        "status": PASS_STATUS,
        **identity,
        "transition_readiness_sha256": _canonical_sha256(dict(transition_readiness)),
        "deployment_snapshot_sha256": deployment_sha,
        "deployment_eligible_during_check": False,
        "game_pk": game_pk,
        "provider_event_id": provider_event_id,
        "event_start_ts": start.isoformat(),
        "quote_observed_at_utc": observed.isoformat(),
        "quote_age_seconds": quote_age,
        "max_quote_age_seconds": MAX_QUOTE_AGE_SECONDS,
        "capture_raw_sha256": raw_sha,
        "runtime_home_model_p": home_p,
        "runtime_away_model_p": away_p,
        "frozen_prediction_home_model_p": frozen_home_p,
        "home_no_vig_probability": home_fair,
        "away_no_vig_probability": away_fair,
        "production_engine_dispatch": PRODUCTION_ENGINE_DISPATCH,
        "production_home_status": home_run.bet_status,
        "production_away_status": away_run.bet_status,
        "runtime_checks": {
            "same_frozen_identity": True,
            "active_model_artifact_matches": True,
            "market_blind_prediction_pit_valid": True,
            "draftkings_paired_quote_identity_valid": True,
            "quote_fresh_at_receipt": True,
            "canonical_production_engine_parity": True,
            "two_sided_model_probability_coherence": True,
            "frozen_devig_pair_valid": True,
            "production_candidate_binding_home": True,
            "production_candidate_binding_away": True,
            "deployment_remained_fail_closed": True,
        },
        "state_transition_apply_now": False,
        "promotion_authority": False,
        "deployment_change_allowed": False,
        "staking_change_allowed": False,
        "official_change_allowed": False,
    }
