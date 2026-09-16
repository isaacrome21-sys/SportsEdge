#!/usr/bin/env python3
"""Settle prospective MLB MONEYLINE evidence and score frozen metric prerequisites.

This job is downstream of Model_P and market capture. It never changes a
prediction or quote, never feeds sportsbook data back into Model_P, and never
grants deployment, staking, promotion, Truth Gate, or OFFICIAL authority.

Completed records require:
- market-blind prospective Model_P with strict PIT timestamps;
- exact model-artifact identity binding;
- DraftKings paired decision quote at the frozen T30 EARLY_ONLY window;
- last actually retained paired pre-first-pitch quote as the close;
- authoritative final MLB StatsAPI settlement with raw-byte SHA provenance.

The cumulative report invokes the already-frozen calibration and CLV evaluators
per model artifact. A metric pass is only a prerequisite for the external Truth
Gate; this script always emits promotion_authority=false.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Callable, Iterable, Mapping
from urllib.request import urlopen

from sportsedge.mlb_moneyline_clv import MLBMoneylineCLVError, evaluate_paired_closes
from sportsedge.mlb_moneyline_evidence import MLBMoneylineEvidenceError, evaluate_moneyline_predictions
from sportsedge.mlb_moneyline_forward_ledger import (
    MLBMoneylineForwardLedgerError,
    assemble_forward_evidence,
    evidence_rows_for_gates,
)

SETTLEMENT_VERSION = "mlb_moneyline_forward_settlement_v1"
DEFAULT_PREDICTION_ROOT = "data/mlb_forward_predictions"
DEFAULT_QUOTE_ROOT = "data/mlb_forward_capture"
DEFAULT_OUTPUT_ROOT = "data/mlb_forward_evidence"
DEFAULT_RAW_ROOT = "data/mlb_forward_settlement_raw"
DEFAULT_REPORT = "artifacts/mlb_moneyline_forward_gate_report.json"
MLB_SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule?sportId=1&gamePk={game_pk}"


class MLBMoneylineSettlementError(RuntimeError):
    pass


def _utc(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise MLBMoneylineSettlementError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _json_files(root: str | Path) -> list[dict[str, Any]]:
    path = Path(root)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for item in sorted(path.rglob("*.json")):
        try:
            row = json.loads(item.read_text(encoding="utf-8"))
        except Exception as exc:
            raise MLBMoneylineSettlementError(f"invalid JSON evidence file: {item}") from exc
        if not isinstance(row, dict):
            raise MLBMoneylineSettlementError(f"evidence row must be an object: {item}")
        rows.append(row)
    return rows


def _write_create_only(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise MLBMoneylineSettlementError(f"immutable evidence collision: {path}")
        return
    try:
        with path.open("xb") as handle:
            handle.write(payload)
    except FileExistsError:
        if path.read_bytes() != payload:
            raise MLBMoneylineSettlementError(f"immutable evidence collision: {path}")


def _canonical_json(row: Mapping[str, Any]) -> bytes:
    return (json.dumps(dict(row), indent=2, sort_keys=True) + "\n").encode("utf-8")


def _game_from_schedule_payload(payload: Mapping[str, Any], game_pk: int) -> Mapping[str, Any]:
    matches = []
    for block in payload.get("dates", []) or []:
        for game in (block or {}).get("games", []) or []:
            try:
                candidate = int(game.get("gamePk"))
            except (TypeError, ValueError):
                continue
            if candidate == int(game_pk):
                matches.append(game)
    if len(matches) != 1:
        raise MLBMoneylineSettlementError(
            f"MLB settlement identity unresolved: game_pk={game_pk} matches={len(matches)}"
        )
    return matches[0]


def fetch_final_settlement(
    game_pk: int,
    *,
    opener: Callable = urlopen,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Any] | None:
    """Fetch one authoritative final settlement and preserve exact source bytes."""
    url = MLB_SCHEDULE_URL.format(game_pk=int(game_pk))
    try:
        with opener(url, timeout=20) as response:
            raw = bytes(response.read())
    except Exception as exc:
        raise MLBMoneylineSettlementError(f"MLB settlement fetch failed for {game_pk}: {exc}") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise MLBMoneylineSettlementError(f"MLB settlement JSON invalid for {game_pk}") from exc
    game = _game_from_schedule_payload(payload, int(game_pk))
    status = str(((game.get("status") or {}).get("abstractGameState")) or "")
    if status != "Final":
        return None
    teams = game.get("teams") or {}
    away = teams.get("away") or {}
    home = teams.get("home") or {}
    try:
        away_id = int((away.get("team") or {}).get("id"))
        home_id = int((home.get("team") or {}).get("id"))
        away_score = int(away.get("score"))
        home_score = int(home.get("score"))
    except (TypeError, ValueError) as exc:
        raise MLBMoneylineSettlementError(f"MLB final score/identity invalid for {game_pk}") from exc
    if away_score == home_score:
        raise MLBMoneylineSettlementError(f"MLB final tied unexpectedly for {game_pk}")
    observed = _utc((clock or (lambda: datetime.now(timezone.utc)))(), "settlement observed_at")
    return {
        "settlement": {
            "game_pk": int(game_pk),
            "status": "FINAL",
            "away_team_id": away_id,
            "home_team_id": home_id,
            "away_score": away_score,
            "home_score": home_score,
        },
        "source_uri": url,
        "observed_at_utc": observed.isoformat(),
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "raw_bytes": raw,
    }


def _prediction_index(rows: Iterable[Mapping[str, Any]]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for row in rows:
        try:
            game_pk = int(row.get("game_pk"))
        except (TypeError, ValueError) as exc:
            raise MLBMoneylineSettlementError("prediction game_pk invalid") from exc
        existing = out.get(game_pk)
        current = dict(row)
        if existing is not None and _canonical_json(existing) != _canonical_json(current):
            raise MLBMoneylineSettlementError(f"conflicting Model_P predictions for game_pk={game_pk}")
        out[game_pk] = current
    return out


def _complete_index(rows: Iterable[Mapping[str, Any]]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for row in rows:
        if row.get("status") != "FORWARD_EVIDENCE_COMPLETE":
            raise MLBMoneylineSettlementError("persisted forward evidence must be complete")
        if row.get("promotion_authority") is not False:
            raise MLBMoneylineSettlementError("persisted forward evidence authority flag invalid")
        try:
            game_pk = int(row.get("game_pk"))
        except (TypeError, ValueError) as exc:
            raise MLBMoneylineSettlementError("persisted evidence game_pk invalid") from exc
        existing = out.get(game_pk)
        current = dict(row)
        if existing is not None and _canonical_json(existing) != _canonical_json(current):
            raise MLBMoneylineSettlementError(f"conflicting completed evidence for game_pk={game_pk}")
        out[game_pk] = current
    return out


def _evaluate_group(records: list[dict[str, Any]]) -> dict[str, Any]:
    calibration_rows, clv_rows = evidence_rows_for_gates(records)
    try:
        calibration = evaluate_moneyline_predictions(calibration_rows, min_sample=200, ece_bins=10)
    except MLBMoneylineEvidenceError as exc:
        calibration = {
            "n": len(calibration_rows),
            "status": "BLOCKED_CALIBRATION_EVALUATOR",
            "reason": str(exc),
            "promotion_authority": False,
        }
    try:
        clv = evaluate_paired_closes(clv_rows, min_mean_clv=.005)
    except MLBMoneylineCLVError as exc:
        clv = {
            "n": len(clv_rows),
            "status": "BLOCKED_CLV_EVALUATOR",
            "reason": str(exc),
            "promotion_authority": False,
        }
    metric_pass = bool(
        calibration.get("sample_gate_pass") is True
        and calibration.get("calibration_gate_pass") is True
        and clv.get("clv_gate_pass") is True
        and int(calibration.get("n", -1)) == int(clv.get("n", -2))
    )
    return {
        "n": len(records),
        "calibration": calibration,
        "clv": clv,
        "metric_prerequisites_pass": metric_pass,
        "external_truth_gate_required": True,
        "promotion_authority": False,
    }


def settle_and_evaluate(
    *,
    prediction_root: str | Path = DEFAULT_PREDICTION_ROOT,
    quote_root: str | Path = DEFAULT_QUOTE_ROOT,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    raw_root: str | Path = DEFAULT_RAW_ROOT,
    report_path: str | Path = DEFAULT_REPORT,
    now: datetime | None = None,
    settlement_fetcher: Callable[[int], dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    now_utc = _utc(now or datetime.now(timezone.utc), "now")
    predictions = _prediction_index(_json_files(prediction_root))
    quotes = _json_files(quote_root)
    completed = _complete_index(_json_files(output_root))
    fetcher = settlement_fetcher or (lambda game_pk: fetch_final_settlement(game_pk))

    retained: list[str] = []
    pending_final: list[int] = []
    pending_start: list[int] = []
    blocked: list[dict[str, Any]] = []

    for game_pk, prediction in sorted(predictions.items()):
        if game_pk in completed:
            continue
        try:
            event_start = datetime.fromisoformat(str(prediction.get("event_start_ts") or "").replace("Z", "+00:00"))
        except ValueError as exc:
            raise MLBMoneylineSettlementError(f"prediction event_start_ts invalid for {game_pk}") from exc
        event_start = _utc(event_start, "event_start_ts")
        if now_utc <= event_start:
            pending_start.append(game_pk)
            continue
        source = fetcher(game_pk)
        if source is None:
            pending_final.append(game_pk)
            continue
        if not isinstance(source, Mapping):
            raise MLBMoneylineSettlementError(f"settlement fetcher contract invalid for {game_pk}")
        settlement = dict(source.get("settlement") or {})
        if int(settlement.get("game_pk", -1)) != game_pk:
            raise MLBMoneylineSettlementError(f"settlement game_pk mismatch for {game_pk}")
        try:
            pred_away_id = int(prediction.get("away_team_id"))
            pred_home_id = int(prediction.get("home_team_id"))
            settle_away_id = int(settlement.get("away_team_id"))
            settle_home_id = int(settlement.get("home_team_id"))
        except (TypeError, ValueError) as exc:
            raise MLBMoneylineSettlementError(f"settlement team identity invalid for {game_pk}") from exc
        if (pred_away_id, pred_home_id) != (settle_away_id, settle_home_id):
            raise MLBMoneylineSettlementError(f"settlement team identity mismatch for {game_pk}")
        try:
            assembled = assemble_forward_evidence(
                prediction=prediction,
                quotes=quotes,
                settlement={
                    "game_pk": game_pk,
                    "status": settlement.get("status"),
                    "away_score": settlement.get("away_score"),
                    "home_score": settlement.get("home_score"),
                },
            )
        except MLBMoneylineForwardLedgerError as exc:
            raise MLBMoneylineSettlementError(f"forward ledger invalid for {game_pk}: {exc}") from exc
        if assembled.get("status") != "FORWARD_EVIDENCE_COMPLETE":
            blocked.append({"game_pk": game_pk, "status": assembled.get("status")})
            continue
        raw = source.get("raw_bytes")
        if not isinstance(raw, (bytes, bytearray)):
            raise MLBMoneylineSettlementError(f"raw settlement bytes required for {game_pk}")
        raw_bytes = bytes(raw)
        raw_sha = hashlib.sha256(raw_bytes).hexdigest()
        if str(source.get("raw_sha256") or "") != raw_sha:
            raise MLBMoneylineSettlementError(f"settlement raw SHA mismatch for {game_pk}")
        observed_at = str(source.get("observed_at_utc") or "")
        observed_dt = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        _utc(observed_dt, "settlement observed_at_utc")
        source_uri = str(source.get("source_uri") or "")
        if not source_uri.startswith("https://statsapi.mlb.com/"):
            raise MLBMoneylineSettlementError(f"settlement source URI invalid for {game_pk}")
        record = {
            **assembled,
            "settlement_version": SETTLEMENT_VERSION,
            "settlement_observed_at_utc": observed_at,
            "settlement_source_uri": source_uri,
            "settlement_raw_sha256": raw_sha,
            "settlement_away_team_id": settle_away_id,
            "settlement_home_team_id": settle_home_id,
            "settlement_source_class": "MLB_STATSAPI_SCHEDULE_FINAL",
            "promotion_authority": False,
        }
        day = event_start.date().isoformat()
        raw_path = Path(raw_root) / day / f"game_{game_pk}__{raw_sha}.json"
        evidence_path = Path(output_root) / day / f"game_{game_pk}.json"
        _write_create_only(raw_path, raw_bytes)
        _write_create_only(evidence_path, _canonical_json(record))
        retained.append(str(evidence_path))
        completed[game_pk] = record

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in completed.values():
        artifact = str(row.get("model_artifact_sha256") or "")
        if len(artifact) != 64:
            raise MLBMoneylineSettlementError("completed evidence missing model_artifact_sha256")
        groups[artifact].append(row)
    artifact_groups = {
        artifact: _evaluate_group(sorted(records, key=lambda row: int(row["game_pk"])))
        for artifact, records in sorted(groups.items())
    }
    any_metric_pass = any(group.get("metric_prerequisites_pass") is True for group in artifact_groups.values())
    report = {
        "schema_version": SETTLEMENT_VERSION,
        "generated_at_utc": now_utc.isoformat(),
        "predictions_seen": len(predictions),
        "quotes_seen": len(quotes),
        "completed_evidence_total": len(completed),
        "new_completed_evidence": len(retained),
        "retained_paths": retained,
        "pending_start_game_pks": pending_start,
        "pending_final_game_pks": pending_final,
        "blocked_games": blocked,
        "artifact_groups": artifact_groups,
        "metric_prerequisites_pass_for_any_artifact": any_metric_pass,
        "status": (
            "METRIC_PREREQUISITES_PASS_EXTERNAL_TRUTH_GATE_REQUIRED"
            if any_metric_pass
            else "FORWARD_EVIDENCE_ACCUMULATING"
        ),
        "external_truth_gate_required": True,
        "deployment_change_allowed_by_this_report": False,
        "staking_change_allowed_by_this_report": False,
        "official_change_allowed_by_this_report": False,
        "promotion_authority": False,
    }
    report_file = Path(report_path)
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--prediction-root", default=DEFAULT_PREDICTION_ROOT)
    ap.add_argument("--quote-root", default=DEFAULT_QUOTE_ROOT)
    ap.add_argument("--output-root", default=DEFAULT_OUTPUT_ROOT)
    ap.add_argument("--raw-root", default=DEFAULT_RAW_ROOT)
    ap.add_argument("--report", default=DEFAULT_REPORT)
    args = ap.parse_args(argv)
    try:
        report = settle_and_evaluate(
            prediction_root=args.prediction_root,
            quote_root=args.quote_root,
            output_root=args.output_root,
            raw_root=args.raw_root,
            report_path=args.report,
        )
    except Exception as exc:
        print(json.dumps({
            "status": "BLOCKED",
            "reason": "BLOCKED_FORWARD_SETTLEMENT_OR_EVALUATION",
            "detail": str(exc),
            "promotion_authority": False,
        }, indent=2, sort_keys=True))
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
