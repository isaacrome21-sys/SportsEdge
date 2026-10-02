"""PIT walk-forward diagnostics for NFL player-prop engines.

This validates predictive distributions without inventing historical sportsbook
lines or prices. It can falsify an engine, but cannot promote one. Market-level
calibration, CLV, ROI, and edge-floor evidence remain separately required.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from math import isfinite, log, sqrt
from typing import Any, Iterable, Mapping

from .prop_engines import MARKETS, PropEngineError, fit_nfl_prop_engine, predict_nfl_prop

VALIDATION_CONTRACT = "NFL_PLAYER_PROP_WALKFORWARD_V1"
_EPS = 1e-9


def _utc(value: Any) -> datetime:
    if isinstance(value, datetime):
        out = value
    else:
        out = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    if out.tzinfo is None or out.utcoffset() is None:
        raise ValueError("PROP_VALIDATION_TIMESTAMP_TIMEZONE_REQUIRED")
    return out.astimezone(timezone.utc)


def _finite(value: Any, reason: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(reason) from exc
    if not isfinite(out):
        raise ValueError(reason)
    return out


def _actual_value(row: Mapping[str, Any], market_id: str) -> float:
    market = market_id.upper()
    if market == "ANYTIME_TD":
        return 1.0 if _finite(row.get("rushing_tds", 0), "PROP_VALIDATION_TD_INVALID") + _finite(row.get("receiving_tds", 0), "PROP_VALIDATION_TD_INVALID") > 0 else 0.0
    field = MARKETS[market][0]
    if row.get(field) in (None, ""):
        raise ValueError(f"PROP_VALIDATION_STAT_MISSING:{field}")
    value = _finite(row.get(field), f"PROP_VALIDATION_STAT_INVALID:{field}")
    if value < 0:
        raise ValueError(f"PROP_VALIDATION_STAT_NEGATIVE:{field}")
    return value


def _player_rows(rows: Iterable[Mapping[str, Any]], player_id: str) -> list[dict[str, Any]]:
    out = [dict(row) for row in rows if str(row.get("player_id") or "").strip() == player_id]
    out.sort(key=lambda row: (_utc(row.get("kickoff_ts")), str(row.get("game_id") or "")))
    return out


def build_prop_walkforward_evidence(
    rows: Iterable[Mapping[str, Any]],
    *,
    player_id: str,
    market_id: str,
    source_manifest_sha256: str,
    min_games: int = 6,
) -> dict[str, Any]:
    market = str(market_id or "").strip().upper()
    if market not in MARKETS:
        raise ValueError(f"PROP_VALIDATION_MARKET_UNSUPPORTED:{market}")
    pid = str(player_id or "").strip()
    if not pid:
        raise ValueError("PROP_VALIDATION_PLAYER_REQUIRED")

    data = _player_rows(rows, pid)
    predictions: list[dict[str, Any]] = []
    for index, heldout in enumerate(data):
        if index < min_games:
            continue
        kickoff = _utc(heldout.get("kickoff_ts"))
        history = data[:index]
        model = fit_nfl_prop_engine(
            history,
            player_id=pid,
            market_id=market,
            as_of=kickoff,
            source_manifest_sha256=source_manifest_sha256,
            min_games=min_games,
        )
        actual = _actual_value(heldout, market)
        row: dict[str, Any] = {
            "game_id": str(heldout.get("game_id") or ""),
            "kickoff_ts": kickoff.isoformat(),
            "actual": actual,
            "model_id": model.model_id,
            "sample_n": model.sample_n,
            "weighted_mean": model.weighted_mean,
            "weighted_variance": model.weighted_variance,
        }
        if market == "ANYTIME_TD":
            pred = predict_nfl_prop(
                model,
                side="YES",
                availability_status="ACTIVE",
                role_confirmed=True,
            )
            p = min(1.0 - _EPS, max(_EPS, pred.model_probability))
            row["model_probability"] = p
            row["brier"] = (p - actual) ** 2
            row["log_loss"] = -(actual * log(p) + (1.0 - actual) * log(1.0 - p))
        else:
            error = model.weighted_mean - actual
            row["absolute_error"] = abs(error)
            row["squared_error"] = error * error
        predictions.append(row)

    if not predictions:
        raise ValueError("PROP_VALIDATION_NO_HELDOUT_ROWS")

    payload: dict[str, Any] = {
        "schema_version": 1,
        "contract": VALIDATION_CONTRACT,
        "status": "DISTRIBUTION_DIAGNOSTIC_ONLY",
        "player_id": pid,
        "market_id": market,
        "heldout_n": len(predictions),
        "predictions": predictions,
        "promotion_eligible": False,
        "truth_gate_eligible": False,
        "promotion_authority": False,
        "market_price_evidence_present": False,
        "clv_evidence_present": False,
        "roi_evidence_present": False,
        "edge_floor_frozen": False,
        "missing_promotion_evidence": [
            "HISTORICAL_DECISION_PROP_LINES_AND_PRICES",
            "HISTORICAL_CLOSE_PROP_LINES_AND_PRICES",
            "MARKET_LEVEL_CALIBRATION",
            "CLV",
            "AFTER_VIG_ROI",
            "FROZEN_EDGE_FLOOR",
        ],
    }
    if market == "ANYTIME_TD":
        payload["metrics"] = {
            "brier": sum(row["brier"] for row in predictions) / len(predictions),
            "log_loss": sum(row["log_loss"] for row in predictions) / len(predictions),
            "observed_rate": sum(row["actual"] for row in predictions) / len(predictions),
            "mean_model_probability": sum(row["model_probability"] for row in predictions) / len(predictions),
        }
    else:
        payload["metrics"] = {
            "mae": sum(row["absolute_error"] for row in predictions) / len(predictions),
            "rmse": sqrt(sum(row["squared_error"] for row in predictions) / len(predictions)),
            "mean_actual": sum(row["actual"] for row in predictions) / len(predictions),
            "mean_prediction": sum(row["weighted_mean"] for row in predictions) / len(predictions),
        }
    return payload
