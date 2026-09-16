"""Runtime binding guard for the MLB MONEYLINE V2 checkpoint evaluator."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from .mlb_model_artifact import mlb_model_artifact_sha256
from .mlb_moneyline_forward_lane import load_forward_lane_binding
from .mlb_moneyline_v2_checkpoint import (
    MLBMoneylineV2CheckpointError,
    evaluate_v2_checkpoints as _evaluate_v2_checkpoints,
)


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
    CR1 clustering.  Every row must also bind to the currently verified model
    artifact, so a model-surface change starts a new evidence clock rather than
    silently pooling old and new predictions.
    """
    rows = [dict(row) for row in evidence_rows]
    active_artifact = mlb_model_artifact_sha256()
    for row in rows:
        if str(row.get("model_artifact_sha256") or "") != active_artifact:
            raise MLBMoneylineV2CheckpointError("model artifact binding mismatch")
        start = _utc(row.get("event_start_ts"), "event_start_ts")
        if str(row.get("slate_date") or "") != start.date().isoformat():
            raise MLBMoneylineV2CheckpointError("slate_date must equal UTC event-start date")

    lane = dict(binding or load_forward_lane_binding())
    lane["model_artifact_sha256"] = active_artifact
    return _evaluate_v2_checkpoints(rows, binding=lane, policy_path=policy_path)
