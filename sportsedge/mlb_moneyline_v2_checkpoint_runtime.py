"""Runtime binding guard and CLI for the MLB MONEYLINE V2 checkpoint evaluator."""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping

from .mlb_model_artifact import mlb_model_artifact_sha256
from .mlb_moneyline_forward_lane import load_forward_lane_binding
from .mlb_moneyline_v2_checkpoint import (
    CHECKPOINT_REPORT_SCHEMA,
    MLBMoneylineV2CheckpointError,
    evaluate_v2_checkpoints as _evaluate_v2_checkpoints,
)

DEFAULT_EVIDENCE_ROOT = "data/mlb_forward_evidence"
DEFAULT_REPORT_PATH = "artifacts/mlb_moneyline_v2_checkpoint_report.json"


def _utc(value: Any, field: str) -> datetime:
    try:
        out = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise MLBMoneylineV2CheckpointError(f"{field}: invalid timestamp") from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise MLBMoneylineV2CheckpointError(f"{field}: timezone required")
    return out.astimezone(timezone.utc)


def evaluate_v2_checkpoints(
    evidence_rows: Iterable[Mapping[str, Any]],
    *,
    binding: Mapping[str, Any] | None = None,
    policy_path: str = "config/promotion_evidence_policy_v2.json",
) -> dict[str, Any]:
    """Evaluate fixed checkpoints after binding rows to the active code artifact.

    ``slate_date`` is validated as the UTC event-start date before it can affect
    CR1 clustering.

    Rows are **split** by ``model_artifact_sha256`` rather than rejected on
    mismatch:

    - **Current-hash rows** form the active evidence clock (starts empty after a
      model-surface change).
    - **Older-hash rows** are reported as closed under the prior engine and are
      never pooled into the active clock.

    This keeps historical evidence honest when the Stage-1 surface changes
    (e.g. full-game dispersion promotion) without mixing two models in one
    checkpoint sample.
    """
    rows = [dict(row) for row in evidence_rows]
    active_artifact = mlb_model_artifact_sha256()

    current_rows: list[dict[str, Any]] = []
    closed_by_hash: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for row in rows:
        start = _utc(row.get("event_start_ts"), "event_start_ts")
        if str(row.get("slate_date") or "") != start.date().isoformat():
            raise MLBMoneylineV2CheckpointError("slate_date must equal UTC event-start date")
        row_hash = str(row.get("model_artifact_sha256") or "")
        if not row_hash:
            raise MLBMoneylineV2CheckpointError("model_artifact_sha256 required on evidence row")
        if row_hash == active_artifact:
            current_rows.append(row)
        else:
            closed_by_hash[row_hash].append(row)

    lane = dict(binding or load_forward_lane_binding())
    lane["model_artifact_sha256"] = active_artifact
    report = _evaluate_v2_checkpoints(current_rows, binding=lane, policy_path=policy_path)

    closed_sections = []
    for prior_hash, prior_rows in sorted(closed_by_hash.items()):
        closed_sections.append({
            "status": "CLOSED_UNDER_PRIOR_ENGINE",
            "model_artifact_sha256": prior_hash,
            "row_count": len(prior_rows),
            "label": (
                "Immutable evidence from a prior model surface; not pooled into "
                "the active moneyline v2 checkpoint clock."
            ),
        })

    report["active_model_artifact_sha256"] = active_artifact
    report["active_clock_row_count"] = len(current_rows)
    report["closed_prior_engine_sections"] = closed_sections
    report["closed_prior_engine_row_count"] = sum(section["row_count"] for section in closed_sections)
    report["prior_engine_rows_excluded_from_active_clock"] = True
    return report


def load_evidence_tree(root: str | Path = DEFAULT_EVIDENCE_ROOT) -> list[dict[str, Any]]:
    """Load the cumulative immutable evidence tree, failing closed on bad JSON."""
    path = Path(root)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for item in sorted(path.rglob("*.json")):
        try:
            value = json.loads(item.read_text(encoding="utf-8"))
        except Exception as exc:
            raise MLBMoneylineV2CheckpointError(f"invalid checkpoint evidence JSON: {item}") from exc
        if not isinstance(value, dict):
            raise MLBMoneylineV2CheckpointError(f"checkpoint evidence JSON object required: {item}")
        rows.append(value)
    return rows


def evaluate_evidence_tree(
    root: str | Path = DEFAULT_EVIDENCE_ROOT,
    *,
    binding: Mapping[str, Any] | None = None,
    policy_path: str = "config/promotion_evidence_policy_v2.json",
) -> dict[str, Any]:
    """Evaluate the on-disk cumulative evidence clock and bind receipt provenance."""
    path = Path(root)
    rows = load_evidence_tree(path)
    report = evaluate_v2_checkpoints(rows, binding=binding, policy_path=policy_path)
    report["source_evidence_root"] = path.as_posix()
    report["source_json_file_count"] = len(rows)
    return report


def _write_report(path: str | Path, report: Mapping[str, Any]) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(dict(report), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate the fixed MLB MONEYLINE V2 50/100/150 forward checkpoints."
    )
    parser.add_argument("--evidence-root", default=DEFAULT_EVIDENCE_ROOT)
    parser.add_argument("--report", default=DEFAULT_REPORT_PATH)
    args = parser.parse_args(argv)

    try:
        report = evaluate_evidence_tree(args.evidence_root)
    except (OSError, MLBMoneylineV2CheckpointError) as exc:
        blocked = {
            "schema_version": CHECKPOINT_REPORT_SCHEMA,
            "status": "BLOCKED_CHECKPOINT_RUNTIME_ERROR",
            "reason": str(exc),
            "source_evidence_root": Path(args.evidence_root).as_posix(),
            "promotion_authority": False,
            "deployment_change_allowed": False,
            "staking_change_allowed": False,
            "official_change_allowed": False,
        }
        _write_report(args.report, blocked)
        print(json.dumps(blocked, indent=2, sort_keys=True))
        return 2

    _write_report(args.report, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
