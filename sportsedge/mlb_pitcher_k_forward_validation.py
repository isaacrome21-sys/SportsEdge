"""Prospective validation primitives for the frozen MLB pitcher-K candidate."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from math import floor, log
from pathlib import Path
from typing import Any, Mapping

from .mlb_pitcher_k_probability_candidate import (
    CANDIDATE_FAMILY,
    FEATURES,
    PitcherKRateFit,
    price_threshold,
)

FREEZE_SCHEMA = "SPORTSEDGE_MLB_PITCHER_K_ATTEMPT1_PASSED_FIT_FREEZE_V1"
FREEZE_STATUS = "FROZEN_AFTER_DEVELOPMENT_PASS_FORWARD_VALIDATION_PENDING"
PREDICTION_SCHEMA = "SPORTSEDGE_MLB_PITCHER_K_FORWARD_PREDICTION_V1"
SETTLEMENT_SCHEMA = "SPORTSEDGE_MLB_PITCHER_K_FORWARD_SETTLEMENT_V1"
DEFAULT_FREEZE = Path("config/research/mlb_pitcher_k_attempt1_passed_fit_freeze_v1.json")


class PitcherKForwardValidationError(ValueError):
    pass


def canonical_sha256(value: Any) -> str:
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _parse_utc(value: Any, field: str) -> datetime:
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise PitcherKForwardValidationError(f"{field} invalid") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise PitcherKForwardValidationError(f"{field} must be timezone-aware")
    return dt.astimezone(timezone.utc)


def _american_decimal(value: Any) -> float:
    try:
        odds = int(value)
    except (TypeError, ValueError) as exc:
        raise PitcherKForwardValidationError("American odds must be integer") from exc
    if odds == 0 or -100 < odds < 100:
        raise PitcherKForwardValidationError("American odds outside supported range")
    return 1.0 + (odds / 100.0 if odds > 0 else 100.0 / abs(odds))


def market_fair_over(over_odds: Any, under_odds: Any) -> float:
    do = _american_decimal(over_odds)
    du = _american_decimal(under_odds)
    qo, qu = 1.0 / do, 1.0 / du
    return float(qo / (qo + qu))


def load_frozen_fit(path: str | Path = DEFAULT_FREEZE) -> tuple[PitcherKRateFit, float, dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema") != FREEZE_SCHEMA or payload.get("status") != FREEZE_STATUS:
        raise PitcherKForwardValidationError("passed-fit freeze identity mismatch")
    if payload.get("candidate_family") != CANDIDATE_FAMILY:
        raise PitcherKForwardValidationError("candidate family mismatch")
    raw = payload.get("final_fit")
    if not isinstance(raw, Mapping):
        raise PitcherKForwardValidationError("final_fit missing")
    fit = PitcherKRateFit(
        candidate_family=CANDIDATE_FAMILY,
        feature_names=tuple(str(v) for v in raw.get("feature_names") or ()),
        means=tuple(float(v) for v in raw.get("means") or ()),
        scales=tuple(float(v) for v in raw.get("scales") or ()),
        coefficients=tuple(float(v) for v in raw.get("coefficients") or ()),
        ridge_alpha=float(raw.get("ridge_alpha")),
        training_rows=int(raw.get("training_rows")),
        training_batters_faced=int(raw.get("training_batters_faced")),
        fit_sha256=str(raw.get("fit_sha256") or ""),
    )
    if fit.feature_names != tuple(FEATURES):
        raise PitcherKForwardValidationError("feature order mismatch")
    identity = {
        "candidate_family": fit.candidate_family,
        "feature_names": list(fit.feature_names),
        "means": list(fit.means),
        "scales": list(fit.scales),
        "coefficients": list(fit.coefficients),
        "ridge_alpha": fit.ridge_alpha,
        "training_rows": fit.training_rows,
        "training_batters_faced": fit.training_batters_faced,
    }
    if canonical_sha256(identity) != fit.fit_sha256:
        raise PitcherKForwardValidationError("frozen fit SHA mismatch")
    concentration = float(raw.get("concentration"))
    return fit, concentration, payload


def build_prediction_receipt(
    *,
    candidate: Mapping[str, Any],
    game_pk: int,
    pitcher_id: int,
    pitcher_team_id: int,
    line: float,
    over_odds: int,
    under_odds: int,
    observed_at: str,
    first_pitch_at: str,
    provider_event_id: str,
    entity_name: str,
    quote_archive_path: str,
    context_proof: Mapping[str, Any],
    statcast_proof: Mapping[str, Any],
    freeze_path: str | Path = DEFAULT_FREEZE,
) -> dict[str, Any]:
    observed = _parse_utc(observed_at, "observed_at")
    first_pitch = _parse_utc(first_pitch_at, "first_pitch_at")
    if observed >= first_pitch:
        raise PitcherKForwardValidationError("prediction quote is not pregame")
    threshold = float(line)
    if threshold < 0 or abs((threshold - floor(threshold)) - 0.5) > 1e-9:
        raise PitcherKForwardValidationError("forward validation requires a half-integer line")
    fit, concentration, freeze = load_frozen_fit(freeze_path)
    priced = price_threshold(candidate, fit, concentration=concentration, line=threshold)
    q_over = market_fair_over(over_odds, under_odds)
    receipt = {
        "schema": PREDICTION_SCHEMA,
        "status": "CAPTURED_PROSPECTIVE",
        "market": "PITCHER_K",
        "game_pk": int(game_pk),
        "pitcher_id": int(pitcher_id),
        "pitcher_team_id": int(pitcher_team_id),
        "entity_name": str(entity_name),
        "provider_event_id": str(provider_event_id),
        "line": threshold,
        "over_odds": int(over_odds),
        "under_odds": int(under_odds),
        "market_fair_p_over": q_over,
        "candidate_p_over": float(priced["candidate_p_over"]),
        "candidate_p_under": float(priced["candidate_p_under"]),
        "candidate_p_push": float(priced["candidate_p_push"]),
        "projected_batters_faced": int(priced["projected_batters_faced"]),
        "predicted_k_per_batter_faced": float(priced["predicted_k_per_batter_faced"]),
        "observed_at_utc": observed.isoformat(),
        "first_pitch_at_utc": first_pitch.isoformat(),
        "fit_sha256": fit.fit_sha256,
        "evaluation_run_id": int((freeze.get("provenance") or {}).get("evaluation_run_id")),
        "quote_archive_path": str(quote_archive_path),
        "context_proof": dict(context_proof),
        "statcast_proof": dict(statcast_proof),
        "authority": {
            "forward_validation_evidence_only": True,
            "production_activation": False,
            "promotion": False,
            "official": False,
        },
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    return receipt


def settle_prediction(
    prediction: Mapping[str, Any],
    *,
    realized_strikeouts: int | None,
    started: bool,
    settled_at: str,
) -> dict[str, Any]:
    if prediction.get("schema") != PREDICTION_SCHEMA:
        raise PitcherKForwardValidationError("unexpected prediction schema")
    settled = _parse_utc(settled_at, "settled_at")
    base = {
        "schema": SETTLEMENT_SCHEMA,
        "prediction_sha256": str(prediction.get("receipt_sha256") or ""),
        "game_pk": int(prediction["game_pk"]),
        "pitcher_id": int(prediction["pitcher_id"]),
        "line": float(prediction["line"]),
        "settled_at_utc": settled.isoformat(),
        "authority": {
            "forward_validation_evidence_only": True,
            "production_activation": False,
            "promotion": False,
            "official": False,
        },
    }
    if not started:
        base.update({"status": "VOID_NOT_STARTER", "realized_strikeouts": None})
        base["receipt_sha256"] = canonical_sha256(base)
        return base
    if realized_strikeouts is None or int(realized_strikeouts) < 0:
        raise PitcherKForwardValidationError("realized strikeouts required for a starting pitcher")
    y_count = int(realized_strikeouts)
    y = 1.0 if y_count > float(prediction["line"]) else 0.0
    p = min(1.0 - 1e-12, max(1e-12, float(prediction["candidate_p_over"])))
    q = min(1.0 - 1e-12, max(1e-12, float(prediction["market_fair_p_over"])))
    ll_candidate = -(y * log(p) + (1.0 - y) * log(1.0 - p))
    ll_market = -(y * log(q) + (1.0 - y) * log(1.0 - q))
    base.update({
        "status": "GRADED",
        "realized_strikeouts": y_count,
        "outcome_over": bool(y),
        "candidate_log_loss": float(ll_candidate),
        "market_log_loss": float(ll_market),
        "candidate_minus_market_log_loss": float(ll_candidate - ll_market),
        "candidate_brier": float((p - y) ** 2),
        "market_brier": float((q - y) ** 2),
    })
    base["receipt_sha256"] = canonical_sha256(base)
    return base
