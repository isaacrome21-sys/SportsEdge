#!/usr/bin/env python3
"""Freeze immutable pregame PAPER decisions for MLB MONEYLINE V2 evidence."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping

from sportsedge.mlb_moneyline_forward_lane import (
    MLBMoneylineForwardLaneError,
    load_forward_lane_binding,
    require_record_binding,
)
from sportsedge.mlb_moneyline_paper_decision import (
    MLBMoneylinePaperDecisionError,
    freeze_paper_decision,
)

DEFAULT_PREDICTION_ROOT = "data/mlb_forward_predictions"
DEFAULT_QUOTE_ROOT = "data/mlb_forward_capture"
DEFAULT_DECISION_ROOT = "data/mlb_forward_decisions"


class PaperDecisionCaptureError(RuntimeError):
    pass


def _json_files(root: str | Path) -> list[dict[str, Any]]:
    path = Path(root)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for item in sorted(path.rglob("*.json")):
        try:
            row = json.loads(item.read_text(encoding="utf-8"))
        except Exception as exc:
            raise PaperDecisionCaptureError(f"invalid JSON: {item}") from exc
        if not isinstance(row, dict):
            raise PaperDecisionCaptureError(f"JSON object required: {item}")
        rows.append(row)
    return rows


def _canonical_bytes(row: Mapping[str, Any]) -> bytes:
    return (json.dumps(dict(row), indent=2, sort_keys=True) + "\n").encode("utf-8")


def _write_create_only(path: Path, row: Mapping[str, Any]) -> bool:
    payload = _canonical_bytes(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise PaperDecisionCaptureError(f"immutable decision collision: {path}")
        return False
    try:
        with path.open("xb") as handle:
            handle.write(payload)
    except FileExistsError:
        if path.read_bytes() != payload:
            raise PaperDecisionCaptureError(f"immutable decision collision: {path}")
        return False
    return True


def _prediction_index(rows: Iterable[Mapping[str, Any]]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for row in rows:
        try:
            game_pk = int(row.get("game_pk"))
        except (TypeError, ValueError) as exc:
            raise PaperDecisionCaptureError("prediction game_pk invalid") from exc
        current = dict(row)
        existing = out.get(game_pk)
        if existing is not None and _canonical_bytes(existing) != _canonical_bytes(current):
            raise PaperDecisionCaptureError(f"conflicting predictions for game_pk={game_pk}")
        out[game_pk] = current
    return out


def _decision_index(rows: Iterable[Mapping[str, Any]], binding: Mapping[str, Any]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    allowed = {"PAPER_BET_FROZEN", "PAPER_PASS_FROZEN", "BLOCKED_MISSED_DECISION_FREEZE"}
    for row in rows:
        if row.get("status") not in allowed:
            raise PaperDecisionCaptureError("persisted decision status invalid")
        try:
            require_record_binding(row, binding)
        except MLBMoneylineForwardLaneError as exc:
            raise PaperDecisionCaptureError(str(exc)) from exc
        try:
            game_pk = int(row.get("game_pk"))
        except (TypeError, ValueError) as exc:
            raise PaperDecisionCaptureError("decision game_pk invalid") from exc
        current = dict(row)
        existing = out.get(game_pk)
        if existing is not None and _canonical_bytes(existing) != _canonical_bytes(current):
            raise PaperDecisionCaptureError(f"conflicting decisions for game_pk={game_pk}")
        out[game_pk] = current
    return out


def capture_decisions(
    *,
    prediction_root: str | Path = DEFAULT_PREDICTION_ROOT,
    quote_root: str | Path = DEFAULT_QUOTE_ROOT,
    decision_root: str | Path = DEFAULT_DECISION_ROOT,
    now: datetime | None = None,
) -> dict[str, Any]:
    freeze_now = now or datetime.now(timezone.utc)
    if freeze_now.tzinfo is None or freeze_now.utcoffset() is None:
        raise PaperDecisionCaptureError("now must be timezone-aware")
    freeze_now = freeze_now.astimezone(timezone.utc)
    binding = load_forward_lane_binding()
    predictions = _prediction_index(_json_files(prediction_root))
    quotes = _json_files(quote_root)
    existing = _decision_index(_json_files(decision_root), binding)

    retained: list[str] = []
    waiting: list[int] = []
    not_due: list[int] = []
    already_present: list[int] = []
    newly_blocked: list[int] = []

    for game_pk, prediction in sorted(predictions.items()):
        if game_pk in existing:
            already_present.append(game_pk)
            continue
        try:
            decision = freeze_paper_decision(
                prediction=prediction,
                quotes=quotes,
                now=freeze_now,
                binding=binding,
            )
        except MLBMoneylinePaperDecisionError as exc:
            raise PaperDecisionCaptureError(f"game_pk={game_pk}: {exc}") from exc
        status = str(decision.get("status") or "")
        if status == "DECISION_NOT_DUE":
            not_due.append(game_pk)
            continue
        if status == "WAITING_FOR_ADMISSIBLE_DECISION_QUOTE":
            waiting.append(game_pk)
            continue
        if status not in {"PAPER_BET_FROZEN", "PAPER_PASS_FROZEN", "BLOCKED_MISSED_DECISION_FREEZE"}:
            raise PaperDecisionCaptureError(f"unexpected decision status for {game_pk}: {status}")
        try:
            start = datetime.fromisoformat(str(prediction.get("event_start_ts") or "").replace("Z", "+00:00"))
        except ValueError as exc:
            raise PaperDecisionCaptureError(f"event_start_ts invalid for {game_pk}") from exc
        if start.tzinfo is None:
            raise PaperDecisionCaptureError(f"event_start_ts timezone missing for {game_pk}")
        day = start.astimezone(timezone.utc).date().isoformat()
        path = Path(decision_root) / day / f"game_{game_pk}.json"
        if _write_create_only(path, decision):
            retained.append(str(path))
            if status == "BLOCKED_MISSED_DECISION_FREEZE":
                newly_blocked.append(game_pk)

    status = "RETAINED" if retained else "NO_DECISION_DUE"
    if newly_blocked:
        status = "BLOCKED_MISSED_DECISION_WINDOW"
    elif not retained and already_present:
        status = "ALREADY_CAPTURED"
    return {
        "status": status,
        "schema_version": "mlb_moneyline_paper_decision_capture_v1",
        "promotion_authority": False,
        "deployment_change_allowed": False,
        "staking_change_allowed": False,
        "official_change_allowed": False,
        "lane_id": binding["lane_id"],
        "lane_definition_sha256": binding["lane_definition_sha256"],
        "market_definition_sha256": binding["market_definition_sha256"],
        "policy_id": binding["policy_id"],
        "policy_sha256": binding["policy_sha256"],
        "predictions_seen": len(predictions),
        "quotes_seen": len(quotes),
        "decisions_retained": len(retained),
        "retained_paths": retained,
        "already_present_game_pks": already_present,
        "waiting_for_quote_game_pks": waiting,
        "not_due_game_pks": not_due,
        "newly_blocked_game_pks": newly_blocked,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prediction-root", default=DEFAULT_PREDICTION_ROOT)
    parser.add_argument("--quote-root", default=DEFAULT_QUOTE_ROOT)
    parser.add_argument("--decision-root", default=DEFAULT_DECISION_ROOT)
    args = parser.parse_args(argv)
    try:
        result = capture_decisions(
            prediction_root=args.prediction_root,
            quote_root=args.quote_root,
            decision_root=args.decision_root,
        )
    except (PaperDecisionCaptureError, MLBMoneylineForwardLaneError) as exc:
        print(json.dumps({
            "status": "BLOCKED",
            "reason": str(exc),
            "promotion_authority": False,
            "staking_change_allowed": False,
            "official_change_allowed": False,
        }, indent=2, sort_keys=True))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 2 if result["status"] == "BLOCKED_MISSED_DECISION_WINDOW" else 0


if __name__ == "__main__":
    sys.exit(main())
