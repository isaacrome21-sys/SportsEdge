"""Capture prospective NHL prop prediction receipts without backfill.

The evaluator contract lives in ``prop_forward_validation``.  This module only
turns an already-computed model payload into immutable pre-puck receipts.  It
never derives probabilities from sportsbook prices, never accepts a caller-
supplied capture timestamp, and never creates settlement rows.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Iterable, Mapping

from sportsedge.sports.nhl.prop_forward_validation import (
    NHLPropForwardValidationError,
    PredictionReceipt,
    prediction_from_mapping,
)


BASELINE_KIND = "MARKET_BLIND"
_FORBIDDEN_SOURCE_FIELDS = frozenset({"captured_at", "source_sha256"})
_REQUIRED_SOURCE_FIELDS = frozenset(
    {
        "market",
        "game_id",
        "subject_id",
        "line",
        "candidate_p",
        "baseline_p",
        "start_time_utc",
        "role_status",
        "model_version",
        "baseline_kind",
    }
)


class NHLPropPredictionCaptureError(NHLPropForwardValidationError):
    """Fail-closed error for prospective prediction capture."""


def _capture_timestamp(value: datetime | None) -> str:
    captured = datetime.now(timezone.utc) if value is None else value
    if captured.tzinfo is None or captured.utcoffset() is None:
        raise NHLPropPredictionCaptureError("capture clock must be timezone-aware")
    return captured.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _source_rows(source_bytes: bytes) -> list[Mapping[str, object]]:
    try:
        payload = json.loads(source_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NHLPropPredictionCaptureError("source payload must be valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise NHLPropPredictionCaptureError("source payload must be a JSON object")
    rows = payload.get("predictions")
    if not isinstance(rows, list) or not rows:
        raise NHLPropPredictionCaptureError("source payload requires a non-empty predictions list")
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise NHLPropPredictionCaptureError(f"predictions[{index}] must be an object")
    return rows


def _validated_prediction(
    mapping: Mapping[str, object], *, context: str
) -> PredictionReceipt:
    try:
        return prediction_from_mapping(mapping)
    except NHLPropForwardValidationError as exc:
        raise NHLPropPredictionCaptureError(f"{context}: {exc}") from exc


def receipts_from_source(
    source_bytes: bytes,
    *,
    captured_at: datetime | None = None,
) -> list[PredictionReceipt]:
    """Create validated receipts from exact source bytes.

    ``captured_at`` exists only for deterministic tests.  Operational callers
    omit it so wall-clock UTC is stamped at execution time.
    """

    rows = _source_rows(source_bytes)
    stamp = _capture_timestamp(captured_at)
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    receipts: list[PredictionReceipt] = []
    seen: set[tuple[str, str, str, float]] = set()

    for index, row in enumerate(rows):
        forbidden = _FORBIDDEN_SOURCE_FIELDS.intersection(row)
        if forbidden:
            fields = ", ".join(sorted(forbidden))
            raise NHLPropPredictionCaptureError(
                f"predictions[{index}] may not supply capture-owned fields: {fields}"
            )
        missing = _REQUIRED_SOURCE_FIELDS.difference(row)
        if missing:
            fields = ", ".join(sorted(missing))
            raise NHLPropPredictionCaptureError(
                f"predictions[{index}] missing required fields: {fields}"
            )
        if str(row["baseline_kind"]).strip().upper() != BASELINE_KIND:
            raise NHLPropPredictionCaptureError(
                f"predictions[{index}] baseline_kind must be {BASELINE_KIND}"
            )

        mapping = {
            "market": row["market"],
            "game_id": row["game_id"],
            "subject_id": row["subject_id"],
            "line": row["line"],
            "candidate_p": row["candidate_p"],
            "baseline_p": row["baseline_p"],
            "captured_at": stamp,
            "start_time_utc": row["start_time_utc"],
            "role_status": row["role_status"],
            "model_version": row["model_version"],
            "source_sha256": source_sha256,
        }
        receipt = _validated_prediction(mapping, context=f"predictions[{index}]")
        if receipt.key in seen:
            raise NHLPropPredictionCaptureError(
                f"duplicate prediction key inside source payload: {receipt.key}"
            )
        seen.add(receipt.key)
        receipts.append(receipt)
    return receipts


def _read_existing(path: Path) -> tuple[str, list[PredictionReceipt]]:
    if not path.exists():
        return "", []
    text = path.read_text(encoding="utf-8")
    receipts: list[PredictionReceipt] = []
    for number, raw in enumerate(text.splitlines(), 1):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise NHLPropPredictionCaptureError(
                f"{path}:{number}: invalid existing JSONL"
            ) from exc
        if not isinstance(value, dict):
            raise NHLPropPredictionCaptureError(
                f"{path}:{number}: existing receipt must be an object"
            )
        receipts.append(
            _validated_prediction(value, context=f"{path}:{number}")
        )
    keys = [receipt.key for receipt in receipts]
    if len(keys) != len(set(keys)):
        raise NHLPropPredictionCaptureError("existing receipt file contains duplicate keys")
    return text, receipts


def append_receipts(path: Path, receipts: Iterable[PredictionReceipt]) -> int:
    """Atomically append validated receipts while preserving all prior bytes."""

    pending = list(receipts)
    if not pending:
        raise NHLPropPredictionCaptureError("no receipts to append")
    for receipt in pending:
        try:
            receipt.validate()
        except NHLPropForwardValidationError as exc:
            raise NHLPropPredictionCaptureError(f"invalid pending receipt: {exc}") from exc

    original, existing = _read_existing(path)
    existing_keys = {receipt.key for receipt in existing}
    pending_keys: set[tuple[str, str, str, float]] = set()
    for receipt in pending:
        if receipt.key in existing_keys or receipt.key in pending_keys:
            raise NHLPropPredictionCaptureError(f"duplicate prediction key: {receipt.key}")
        pending_keys.add(receipt.key)

    rendered = original
    if rendered and not rendered.endswith("\n"):
        rendered += "\n"
    rendered += "".join(
        json.dumps(asdict(receipt), sort_keys=True, separators=(",", ":")) + "\n"
        for receipt in pending
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as handle:
            temp_name = handle.name
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)
    return len(pending)
