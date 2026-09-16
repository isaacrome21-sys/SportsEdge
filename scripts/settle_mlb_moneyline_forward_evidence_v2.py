#!/usr/bin/env python3
"""Settle only pregame-frozen MLB MONEYLINE V2 PAPER bets.

Legacy reconstructed decisions are never reinterpreted under Promotion Evidence
Policy V2. PAPER passes and BLOCKED rows remain auditable but do not enter the
graded-bet denominator. Missing closes remain in the denominator and are excluded
from CLV, matching the active V2 policy.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Callable, Iterable, Mapping

from scripts.settle_mlb_moneyline_forward_evidence import fetch_final_settlement
from sportsedge.mlb_moneyline_forward_lane import (
    MLBMoneylineForwardLaneError,
    load_forward_lane_binding,
    require_record_binding,
)
from sportsedge.mlb_moneyline_v2_settlement import (
    MLBMoneylineV2SettlementError,
    complete_v2_evidence,
)

SETTLEMENT_RUNNER_VERSION = "mlb_moneyline_forward_settlement_runner_v2"
DEFAULT_PREDICTION_ROOT = "data/mlb_forward_predictions"
DEFAULT_QUOTE_ROOT = "data/mlb_forward_capture"
DEFAULT_DECISION_ROOT = "data/mlb_forward_decisions"
DEFAULT_OUTPUT_ROOT = "data/mlb_forward_evidence"
DEFAULT_RAW_ROOT = "data/mlb_forward_settlement_raw"
DEFAULT_REPORT = "artifacts/mlb_moneyline_forward_gate_report_v2.json"


class MLBMoneylineV2RunnerError(RuntimeError):
    pass


def _utc(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise MLBMoneylineV2RunnerError(f"{field} must be timezone-aware")
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
            raise MLBMoneylineV2RunnerError(f"invalid JSON: {item}") from exc
        if not isinstance(row, dict):
            raise MLBMoneylineV2RunnerError(f"JSON object required: {item}")
        rows.append(row)
    return rows


def _canonical_bytes(row: Mapping[str, Any]) -> bytes:
    return (json.dumps(dict(row), indent=2, sort_keys=True) + "\n").encode("utf-8")


def _write_create_only(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise MLBMoneylineV2RunnerError(f"immutable evidence collision: {path}")
        return
    try:
        with path.open("xb") as handle:
            handle.write(payload)
    except FileExistsError:
        if path.read_bytes() != payload:
            raise MLBMoneylineV2RunnerError(f"immutable evidence collision: {path}")


def _prediction_index(rows: Iterable[Mapping[str, Any]]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for row in rows:
        try:
            game_pk = int(row.get("game_pk"))
        except (TypeError, ValueError) as exc:
            raise MLBMoneylineV2RunnerError("prediction game_pk invalid") from exc
        current = dict(row)
        if game_pk in out and _canonical_bytes(out[game_pk]) != _canonical_bytes(current):
            raise MLBMoneylineV2RunnerError(f"conflicting prediction for game_pk={game_pk}")
        out[game_pk] = current
    return out


def _decision_index(rows: Iterable[Mapping[str, Any]], binding: Mapping[str, Any]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    allowed = {"PAPER_BET_FROZEN", "PAPER_PASS_FROZEN", "BLOCKED_MISSED_DECISION_FREEZE"}
    for row in rows:
        if row.get("status") not in allowed:
            raise MLBMoneylineV2RunnerError("decision status invalid")
        try:
            require_record_binding(row, binding)
        except MLBMoneylineForwardLaneError as exc:
            raise MLBMoneylineV2RunnerError(str(exc)) from exc
        try:
            game_pk = int(row.get("game_pk"))
        except (TypeError, ValueError) as exc:
            raise MLBMoneylineV2RunnerError("decision game_pk invalid") from exc
        current = dict(row)
        if game_pk in out and _canonical_bytes(out[game_pk]) != _canonical_bytes(current):
            raise MLBMoneylineV2RunnerError(f"conflicting decision for game_pk={game_pk}")
        out[game_pk] = current
    return out


def _completed_index(rows: Iterable[Mapping[str, Any]], binding: Mapping[str, Any]) -> tuple[dict[int, dict[str, Any]], int]:
    out: dict[int, dict[str, Any]] = {}
    legacy = 0
    for row in rows:
        if row.get("status") != "FORWARD_EVIDENCE_COMPLETE_V2":
            legacy += 1
            continue
        try:
            require_record_binding(row, binding)
        except MLBMoneylineForwardLaneError as exc:
            raise MLBMoneylineV2RunnerError(str(exc)) from exc
        try:
            game_pk = int(row.get("game_pk"))
        except (TypeError, ValueError) as exc:
            raise MLBMoneylineV2RunnerError("completed V2 game_pk invalid") from exc
        current = dict(row)
        if game_pk in out and _canonical_bytes(out[game_pk]) != _canonical_bytes(current):
            raise MLBMoneylineV2RunnerError(f"conflicting V2 evidence for game_pk={game_pk}")
        out[game_pk] = current
    return out, legacy


def _next_checkpoint(n: int) -> int | None:
    for checkpoint in (50, 100, 150):
        if n < checkpoint:
            return checkpoint
    return None


def settle_v2(
    *,
    prediction_root: str | Path = DEFAULT_PREDICTION_ROOT,
    quote_root: str | Path = DEFAULT_QUOTE_ROOT,
    decision_root: str | Path = DEFAULT_DECISION_ROOT,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    raw_root: str | Path = DEFAULT_RAW_ROOT,
    report_path: str | Path = DEFAULT_REPORT,
    now: datetime | None = None,
    settlement_fetcher: Callable[[int], Mapping[str, Any] | None] | None = None,
) -> dict[str, Any]:
    now_utc = _utc(now or datetime.now(timezone.utc), "now")
    binding = load_forward_lane_binding()
    predictions = _prediction_index(_json_files(prediction_root))
    quotes = _json_files(quote_root)
    decisions = _decision_index(_json_files(decision_root), binding)
    completed, legacy_count = _completed_index(_json_files(output_root), binding)
    fetcher = settlement_fetcher or (lambda game_pk: fetch_final_settlement(game_pk))

    frozen_bets = [row for row in decisions.values() if row.get("status") == "PAPER_BET_FROZEN"]
    paper_passes = [row for row in decisions.values() if row.get("status") == "PAPER_PASS_FROZEN"]
    blocked_decisions = [row for row in decisions.values() if row.get("status") == "BLOCKED_MISSED_DECISION_FREEZE"]
    retained: list[str] = []
    pending_start: list[int] = []
    pending_final: list[int] = []

    for decision in sorted(frozen_bets, key=lambda row: int(row["game_pk"])):
        game_pk = int(decision["game_pk"])
        if game_pk in completed:
            continue
        prediction = predictions.get(game_pk)
        if prediction is None:
            raise MLBMoneylineV2RunnerError(f"missing frozen prediction for graded decision game_pk={game_pk}")
        start = datetime.fromisoformat(str(decision.get("event_start_ts") or "").replace("Z", "+00:00"))
        start = _utc(start, "event_start_ts")
        if now_utc <= start:
            pending_start.append(game_pk)
            continue
        source = fetcher(game_pk)
        if source is None:
            pending_final.append(game_pk)
            continue
        if not isinstance(source, Mapping):
            raise MLBMoneylineV2RunnerError(f"settlement source invalid for {game_pk}")
        settlement = dict(source.get("settlement") or {})
        try:
            pred_away_id = int(prediction.get("away_team_id"))
            pred_home_id = int(prediction.get("home_team_id"))
            settle_away_id = int(settlement.get("away_team_id"))
            settle_home_id = int(settlement.get("home_team_id"))
        except (TypeError, ValueError) as exc:
            raise MLBMoneylineV2RunnerError(f"settlement team identity invalid for {game_pk}") from exc
        if (pred_away_id, pred_home_id) != (settle_away_id, settle_home_id):
            raise MLBMoneylineV2RunnerError(f"settlement team identity mismatch for {game_pk}")
        try:
            record = complete_v2_evidence(
                decision=decision,
                prediction=prediction,
                quotes=quotes,
                settlement={
                    "game_pk": game_pk,
                    "status": settlement.get("status"),
                    "away_score": settlement.get("away_score"),
                    "home_score": settlement.get("home_score"),
                },
                binding=binding,
            )
        except MLBMoneylineV2SettlementError as exc:
            raise MLBMoneylineV2RunnerError(f"V2 settlement invalid for {game_pk}: {exc}") from exc
        raw = source.get("raw_bytes")
        if not isinstance(raw, (bytes, bytearray)):
            raise MLBMoneylineV2RunnerError(f"raw settlement bytes required for {game_pk}")
        raw_bytes = bytes(raw)
        raw_sha = hashlib.sha256(raw_bytes).hexdigest()
        if str(source.get("raw_sha256") or "") != raw_sha:
            raise MLBMoneylineV2RunnerError(f"settlement raw SHA mismatch for {game_pk}")
        source_uri = str(source.get("source_uri") or "")
        if not source_uri.startswith("https://statsapi.mlb.com/"):
            raise MLBMoneylineV2RunnerError(f"settlement source URI invalid for {game_pk}")
        observed_at = str(source.get("observed_at_utc") or "")
        _ts = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        _utc(_ts, "settlement observed_at_utc")
        record.update({
            "settlement_runner_version": SETTLEMENT_RUNNER_VERSION,
            "settlement_observed_at_utc": observed_at,
            "settlement_source_uri": source_uri,
            "settlement_raw_sha256": raw_sha,
            "settlement_away_team_id": settle_away_id,
            "settlement_home_team_id": settle_home_id,
            "settlement_source_class": "MLB_STATSAPI_SCHEDULE_FINAL",
        })
        day = str(decision.get("slate_date") or start.date().isoformat())
        raw_path = Path(raw_root) / day / f"game_{game_pk}__{raw_sha}.json"
        evidence_path = Path(output_root) / day / f"game_{game_pk}__v2.json"
        _write_create_only(raw_path, raw_bytes)
        _write_create_only(evidence_path, _canonical_bytes(record))
        retained.append(str(evidence_path))
        completed[game_pk] = record

    completed_rows = list(completed.values())
    closes = [row for row in completed_rows if row.get("close_status") == "AVAILABLE"]
    clv_values = [float(row["clv_probability_points"]) for row in closes]
    roi_values = [float(row["paper_roi_fraction_per_1u"]) for row in completed_rows]
    n = len(completed_rows)
    report = {
        "schema_version": SETTLEMENT_RUNNER_VERSION,
        "generated_at_utc": now_utc.isoformat(),
        "active_policy_id": binding["policy_id"],
        "policy_sha256": binding["policy_sha256"],
        "lane_id": binding["lane_id"],
        "lane_definition_sha256": binding["lane_definition_sha256"],
        "market_definition_sha256": binding["market_definition_sha256"],
        "predictions_seen": len(predictions),
        "quotes_seen": len(quotes),
        "decisions_seen": len(decisions),
        "paper_bets_frozen": len(frozen_bets),
        "paper_passes_frozen": len(paper_passes),
        "blocked_decisions": len(blocked_decisions),
        "completed_v2_graded_bets": n,
        "new_completed_v2_bets": len(retained),
        "retained_paths": retained,
        "legacy_non_v2_completed_rows_ignored": legacy_count,
        "pending_start_game_pks": pending_start,
        "pending_final_game_pks": pending_final,
        "close_rows_available": len(closes),
        "close_coverage": (len(closes) / n) if n else 0.0,
        "mean_clv_probability_points": (sum(clv_values) / len(clv_values)) if clv_values else None,
        "mean_paper_roi_fraction_per_1u": (sum(roi_values) / len(roi_values)) if roi_values else None,
        "fixed_checkpoints": [50, 100, 150],
        "next_checkpoint": _next_checkpoint(n),
        "checkpoint_evaluator_status": "V2_CHECKPOINT_EVALUATOR_REQUIRED",
        "promotion_authority": False,
        "deployment_change_allowed": False,
        "staking_change_allowed": False,
        "official_change_allowed": False,
        "status": "V2_FORWARD_EVIDENCE_ACCUMULATING",
    }
    target = Path(report_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prediction-root", default=DEFAULT_PREDICTION_ROOT)
    parser.add_argument("--quote-root", default=DEFAULT_QUOTE_ROOT)
    parser.add_argument("--decision-root", default=DEFAULT_DECISION_ROOT)
    parser.add_argument("--output-root", default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--raw-root", default=DEFAULT_RAW_ROOT)
    parser.add_argument("--report", default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    try:
        report = settle_v2(
            prediction_root=args.prediction_root,
            quote_root=args.quote_root,
            decision_root=args.decision_root,
            output_root=args.output_root,
            raw_root=args.raw_root,
            report_path=args.report,
        )
    except (MLBMoneylineV2RunnerError, MLBMoneylineForwardLaneError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc), "promotion_authority": False}, indent=2, sort_keys=True))
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
