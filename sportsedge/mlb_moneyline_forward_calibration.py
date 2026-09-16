"""Prospective calibration settlement for the market-blind MLB MONEYLINE Model_P.

This lane grades every immutable prospective Model_P prediction, not only bets that
clear an edge floor.  That keeps calibration evidence independent of downstream
market selection.  It never consumes sportsbook prices and never grants promotion,
deployment, staking, Truth Gate, or OFFICIAL authority.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from math import isfinite
from pathlib import Path
import sys
from typing import Any, Callable, Iterable, Mapping

from scripts.settle_mlb_moneyline_forward_evidence import fetch_final_settlement
from sportsedge.mlb_model_artifact import mlb_model_artifact_sha256
from sportsedge.mlb_moneyline_evidence import (
    EVIDENCE_VERSION,
    MLBMoneylineEvidenceError,
    evaluate_moneyline_predictions,
)

CALIBRATION_ROW_SCHEMA = "mlb_moneyline_forward_calibration_v1"
CALIBRATION_RUNNER_SCHEMA = "mlb_moneyline_forward_calibration_runner_v1"
PREDICTION_SCHEMA = "mlb_moneyline_forward_model_p_v2_production_parity"
DEFAULT_PREDICTION_ROOT = "data/mlb_forward_predictions"
DEFAULT_CALIBRATION_ROOT = "data/mlb_forward_calibration"
DEFAULT_RAW_ROOT = "data/mlb_forward_calibration_raw"
DEFAULT_REPORT = "artifacts/mlb_moneyline_forward_calibration_report.json"


class MLBMoneylineForwardCalibrationError(RuntimeError):
    pass


def _utc(value: Any, field: str) -> datetime:
    try:
        out = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise MLBMoneylineForwardCalibrationError(f"{field}: invalid timestamp") from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise MLBMoneylineForwardCalibrationError(f"{field}: timezone required")
    return out.astimezone(timezone.utc)


def _json_files(root: str | Path) -> list[dict[str, Any]]:
    path = Path(root)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for item in sorted(path.rglob("*.json")):
        try:
            row = json.loads(item.read_text(encoding="utf-8"))
        except Exception as exc:
            raise MLBMoneylineForwardCalibrationError(f"invalid JSON: {item}") from exc
        if not isinstance(row, dict):
            raise MLBMoneylineForwardCalibrationError(f"JSON object required: {item}")
        rows.append(row)
    return rows


def _canonical_bytes(row: Mapping[str, Any]) -> bytes:
    return (json.dumps(dict(row), indent=2, sort_keys=True) + "\n").encode("utf-8")


def _canonical_sha256(row: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(row)).hexdigest()


def _write_create_only(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise MLBMoneylineForwardCalibrationError(f"immutable calibration collision: {path}")
        return
    try:
        with path.open("xb") as handle:
            handle.write(payload)
    except FileExistsError:
        if path.read_bytes() != payload:
            raise MLBMoneylineForwardCalibrationError(f"immutable calibration collision: {path}")


def _prediction(row: Mapping[str, Any], active_artifact: str) -> dict[str, Any]:
    if row.get("schema_version") != PREDICTION_SCHEMA:
        raise MLBMoneylineForwardCalibrationError("unsupported prospective prediction schema")
    if row.get("evidence_disposition") != "FORWARD_MODEL_P_PREDICTION":
        raise MLBMoneylineForwardCalibrationError("prospective Model_P disposition required")
    if row.get("market_blind") is not True or row.get("promotion_authority") is not False:
        raise MLBMoneylineForwardCalibrationError("market-blind non-authoritative prediction required")
    if str(row.get("market") or "") != "MONEYLINE" or str(row.get("model_side") or "") != "HOME":
        raise MLBMoneylineForwardCalibrationError("fixed HOME MONEYLINE prediction required")
    if str(row.get("model_artifact_sha256") or "") != active_artifact:
        raise MLBMoneylineForwardCalibrationError("prediction model artifact binding mismatch")
    try:
        game_pk = int(row.get("game_pk"))
        away_id = int(row.get("away_team_id"))
        home_id = int(row.get("home_team_id"))
        model_p = float(row.get("model_p"))
    except (TypeError, ValueError) as exc:
        raise MLBMoneylineForwardCalibrationError("prediction identity/probability invalid") from exc
    if not isfinite(model_p) or not 0.0 < model_p < 1.0:
        raise MLBMoneylineForwardCalibrationError("prediction model_p invalid")
    feature_asof = _utc(row.get("feature_asof_ts"), "feature_asof_ts")
    generated = _utc(row.get("prediction_generated_at_utc"), "prediction_generated_at_utc")
    start = _utc(row.get("event_start_ts"), "event_start_ts")
    if not feature_asof < start:
        raise MLBMoneylineForwardCalibrationError("PIT_LEAKAGE")
    if not generated < start:
        raise MLBMoneylineForwardCalibrationError("prediction generated after start")
    return {
        "game_pk": game_pk,
        "away_team_id": away_id,
        "home_team_id": home_id,
        "away_team": str(row.get("away_team") or ""),
        "home_team": str(row.get("home_team") or ""),
        "model_p": model_p,
        "feature_asof_ts": feature_asof,
        "prediction_generated_at_utc": generated,
        "event_start_ts": start,
        "prediction_record_sha256": _canonical_sha256(row),
        "source_record": dict(row),
    }


def _existing_calibration(rows: Iterable[Mapping[str, Any]], active_artifact: str) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for raw in rows:
        if raw.get("schema_version") != CALIBRATION_ROW_SCHEMA:
            raise MLBMoneylineForwardCalibrationError("unknown calibration row schema")
        artifact = str(raw.get("model_artifact_sha256") or "")
        if artifact != active_artifact:
            continue
        if raw.get("market_blind") is not True or raw.get("promotion_authority") is not False:
            raise MLBMoneylineForwardCalibrationError("calibration row authority/market-blind flags invalid")
        try:
            game_pk = int(raw.get("game_pk"))
        except (TypeError, ValueError) as exc:
            raise MLBMoneylineForwardCalibrationError("calibration game_pk invalid") from exc
        row = dict(raw)
        if game_pk in out and _canonical_bytes(out[game_pk]) != _canonical_bytes(row):
            raise MLBMoneylineForwardCalibrationError("DUPLICATE_OR_MUTATED_CALIBRATION_ROW")
        out[game_pk] = row
    return out


def settle_forward_calibration(
    *,
    prediction_root: str | Path = DEFAULT_PREDICTION_ROOT,
    calibration_root: str | Path = DEFAULT_CALIBRATION_ROOT,
    raw_root: str | Path = DEFAULT_RAW_ROOT,
    report_path: str | Path = DEFAULT_REPORT,
    now: datetime | None = None,
    settlement_fetcher: Callable[[int], Mapping[str, Any] | None] | None = None,
) -> dict[str, Any]:
    now_utc = _utc(now or datetime.now(timezone.utc), "now")
    active_artifact = mlb_model_artifact_sha256()
    predictions: dict[int, dict[str, Any]] = {}
    for raw in _json_files(prediction_root):
        parsed = _prediction(raw, active_artifact)
        game_pk = int(parsed["game_pk"])
        if game_pk in predictions and predictions[game_pk]["prediction_record_sha256"] != parsed["prediction_record_sha256"]:
            raise MLBMoneylineForwardCalibrationError("conflicting prospective prediction for game")
        predictions[game_pk] = parsed

    completed = _existing_calibration(_json_files(calibration_root), active_artifact)
    fetcher = settlement_fetcher or (lambda game_pk: fetch_final_settlement(game_pk))
    retained: list[str] = []
    pending_start: list[int] = []
    pending_final: list[int] = []

    for game_pk, pred in sorted(predictions.items()):
        if game_pk in completed:
            continue
        start = pred["event_start_ts"]
        if now_utc <= start:
            pending_start.append(game_pk)
            continue
        source = fetcher(game_pk)
        if source is None:
            pending_final.append(game_pk)
            continue
        if not isinstance(source, Mapping):
            raise MLBMoneylineForwardCalibrationError(f"settlement source invalid for {game_pk}")
        settlement = dict(source.get("settlement") or {})
        try:
            settle_away_id = int(settlement.get("away_team_id"))
            settle_home_id = int(settlement.get("home_team_id"))
            away_score = int(settlement.get("away_score"))
            home_score = int(settlement.get("home_score"))
        except (TypeError, ValueError) as exc:
            raise MLBMoneylineForwardCalibrationError(f"settlement identity/score invalid for {game_pk}") from exc
        if (settle_away_id, settle_home_id) != (pred["away_team_id"], pred["home_team_id"]):
            raise MLBMoneylineForwardCalibrationError(f"settlement team identity mismatch for {game_pk}")
        if str(settlement.get("status") or "").upper() != "FINAL" or away_score == home_score:
            raise MLBMoneylineForwardCalibrationError(f"FINAL non-tied MLB settlement required for {game_pk}")
        raw = source.get("raw_bytes")
        if not isinstance(raw, (bytes, bytearray)):
            raise MLBMoneylineForwardCalibrationError(f"raw settlement bytes required for {game_pk}")
        raw_bytes = bytes(raw)
        raw_sha = hashlib.sha256(raw_bytes).hexdigest()
        if str(source.get("raw_sha256") or "") != raw_sha:
            raise MLBMoneylineForwardCalibrationError(f"settlement raw SHA mismatch for {game_pk}")
        source_uri = str(source.get("source_uri") or "")
        if not source_uri.startswith("https://statsapi.mlb.com/"):
            raise MLBMoneylineForwardCalibrationError(f"settlement source URI invalid for {game_pk}")
        settlement_observed = _utc(source.get("observed_at_utc"), "settlement observed_at_utc")
        row = {
            "schema_version": CALIBRATION_ROW_SCHEMA,
            "status": "FORWARD_CALIBRATION_COMPLETE",
            "market": "MONEYLINE",
            "model_side": "HOME",
            "market_blind": True,
            "promotion_authority": False,
            "deployment_change_allowed": False,
            "staking_change_allowed": False,
            "official_change_allowed": False,
            "game_pk": game_pk,
            "away_team_id": pred["away_team_id"],
            "home_team_id": pred["home_team_id"],
            "away_team": pred["away_team"],
            "home_team": pred["home_team"],
            "model_artifact_sha256": active_artifact,
            "model_p": pred["model_p"],
            "outcome": 1 if home_score > away_score else 0,
            "feature_asof_ts": pred["feature_asof_ts"].isoformat(),
            "prediction_generated_at_utc": pred["prediction_generated_at_utc"].isoformat(),
            "event_start_ts": pred["event_start_ts"].isoformat(),
            "prediction_record_sha256": pred["prediction_record_sha256"],
            "settlement_observed_at_utc": settlement_observed.isoformat(),
            "settlement_source_uri": source_uri,
            "settlement_raw_sha256": raw_sha,
            "settlement_away_score": away_score,
            "settlement_home_score": home_score,
            "calibration_evaluator_version": EVIDENCE_VERSION,
        }
        day = pred["event_start_ts"].date().isoformat()
        raw_path = Path(raw_root) / day / f"game_{game_pk}__{raw_sha}.json"
        out_path = Path(calibration_root) / day / f"game_{game_pk}__{active_artifact[:12]}.json"
        _write_create_only(raw_path, raw_bytes)
        _write_create_only(out_path, _canonical_bytes(row))
        retained.append(str(out_path))
        completed[game_pk] = row

    current_rows = [completed[key] for key in sorted(completed)]
    try:
        metrics = evaluate_moneyline_predictions(current_rows, min_sample=200, ece_bins=10)
    except MLBMoneylineEvidenceError as exc:
        raise MLBMoneylineForwardCalibrationError(str(exc)) from exc
    report = {
        "schema_version": CALIBRATION_RUNNER_SCHEMA,
        "generated_at_utc": now_utc.isoformat(),
        "model_artifact_sha256": active_artifact,
        "predictions_seen_current_artifact": len(predictions),
        "completed_calibration_rows": len(current_rows),
        "new_completed_calibration_rows": len(retained),
        "retained_paths": retained,
        "pending_start_game_pks": pending_start,
        "pending_final_game_pks": pending_final,
        "calibration_metrics": metrics,
        "status": "CALIBRATION_GATE_PASS" if metrics.get("sample_gate_pass") and metrics.get("calibration_gate_pass") else "FORWARD_CALIBRATION_ACCUMULATING",
        "promotion_authority": False,
        "deployment_change_allowed": False,
        "staking_change_allowed": False,
        "official_change_allowed": False,
    }
    target = Path(report_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prediction-root", default=DEFAULT_PREDICTION_ROOT)
    parser.add_argument("--calibration-root", default=DEFAULT_CALIBRATION_ROOT)
    parser.add_argument("--raw-root", default=DEFAULT_RAW_ROOT)
    parser.add_argument("--report", default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    try:
        report = settle_forward_calibration(
            prediction_root=args.prediction_root,
            calibration_root=args.calibration_root,
            raw_root=args.raw_root,
            report_path=args.report,
        )
    except Exception as exc:
        blocked = {
            "schema_version": CALIBRATION_RUNNER_SCHEMA,
            "status": "BLOCKED_CALIBRATION_RUNTIME_ERROR",
            "reason": str(exc),
            "promotion_authority": False,
            "deployment_change_allowed": False,
            "staking_change_allowed": False,
            "official_change_allowed": False,
        }
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps(blocked, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(blocked, indent=2, sort_keys=True))
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
