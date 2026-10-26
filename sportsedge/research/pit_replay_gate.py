"""Fail-closed point-in-time *metadata* gate for chronological research replay.

Metadata validation is not independent authentication of sportsbook or source
receipts. This module neither changes production authority nor computes CLV.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

REQUIRED = (
    "sport", "market", "event_id", "selection_id", "model_version",
    "model_hash", "model_frozen_at", "event_start_ts", "decision_ts",
    "feature_asof_ts", "settled_at", "source_receipt_id", "settlement_status",
    "outcome",
)
SPORTS = frozenset({"MLB", "NFL", "CFB", "NBA", "NHL", "CBB"})
SETTLEMENT = {"WIN": 1, "LOSS": 0, "PUSH": None, "VOID": None}


class PITReplayError(ValueError):
    """A replay cannot claim a chronological holdout with these inputs."""


def _timestamp(value: Any, name: str) -> datetime:
    if not isinstance(value, (str, datetime)):
        raise PITReplayError(f"{name}:MISSING_OR_INVALID")
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PITReplayError(f"{name}:INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PITReplayError(f"{name}:TIMEZONE_REQUIRED")
    return parsed.astimezone(timezone.utc)


def _text(row: Mapping[str, Any], name: str) -> str:
    value = row.get(name)
    if not isinstance(value, str) or not value.strip():
        raise PITReplayError(f"{name}:NONBLANK_STRING_REQUIRED")
    return value.strip()


def partition_chronological_replay(
    rows: Iterable[Mapping[str, Any]], *, holdout_start: str,
) -> dict[str, Any]:
    """Validate and split complete settled rows by *event* start.

    Returns original mappings for training and holdout. Training rows must
    have settled strictly before the holdout boundary. A frozen model version
    must predate the holdout; model/source authenticity is not proven here.
    """
    cutoff = _timestamp(holdout_start, "holdout_start")
    train, holdout = [], []
    identities, event_starts, versions = set(), {}, {}
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise PITReplayError(f"row[{index}]:NOT_A_MAPPING")
        for key in REQUIRED:
            if key not in row:
                raise PITReplayError(f"row[{index}]:{key}:MISSING")
        sport = _text(row, "sport").upper()
        if sport not in SPORTS:
            raise PITReplayError(f"row[{index}]:SPORT_UNSUPPORTED:{sport}")
        market = _text(row, "market").upper()
        event_id = _text(row, "event_id")
        selection_id = _text(row, "selection_id")
        version = _text(row, "model_version")
        model_hash = _text(row, "model_hash")
        _text(row, "source_receipt_id")
        status = _text(row, "settlement_status").upper()
        if status not in SETTLEMENT:
            raise PITReplayError(f"row[{index}]:SETTLEMENT_UNRESOLVED")
        expected = SETTLEMENT[status]
        actual = row["outcome"]
        if expected is None:
            if actual is not None:
                raise PITReplayError(f"row[{index}]:SETTLEMENT_OUTCOME_CONFLICT")
        elif type(actual) is not int or actual != expected:
            raise PITReplayError(f"row[{index}]:SETTLEMENT_OUTCOME_CONFLICT")
        start = _timestamp(row["event_start_ts"], "event_start_ts")
        decision = _timestamp(row["decision_ts"], "decision_ts")
        features = _timestamp(row["feature_asof_ts"], "feature_asof_ts")
        frozen = _timestamp(row["model_frozen_at"], "model_frozen_at")
        settled = _timestamp(row["settled_at"], "settled_at")
        if not (features <= decision < start <= settled):
            raise PITReplayError(f"row[{index}]:FEATURE_DECISION_EVENT_SETTLEMENT_ORDER")
        if not frozen <= decision:
            raise PITReplayError(f"row[{index}]:MODEL_FROZEN_AFTER_DECISION")
        if not frozen < cutoff:
            raise PITReplayError(f"row[{index}]:MODEL_NOT_FROZEN_BEFORE_HOLDOUT")
        key = (sport, market, event_id, selection_id, version)
        if key in identities:
            raise PITReplayError(f"row[{index}]:DUPLICATE_PREDICTION_IDENTITY")
        identities.add(key)
        event_key = (sport, event_id)
        if event_key in event_starts and event_starts[event_key] != start:
            raise PITReplayError(f"row[{index}]:CONFLICTING_EVENT_START")
        event_starts[event_key] = start
        version_key = (sport, market, version)
        if version_key in versions and versions[version_key] != (model_hash, frozen):
            raise PITReplayError(f"row[{index}]:MODEL_VERSION_FINGERPRINT_DRIFT")
        versions[version_key] = (model_hash, frozen)
        if start < cutoff:
            if settled >= cutoff:
                raise PITReplayError(f"row[{index}]:TRAINING_LABEL_NOT_AVAILABLE_AT_CUTOFF")
            train.append(row)
        else:
            holdout.append(row)
    if not train:
        raise PITReplayError("NO_CHRONOLOGICAL_TRAIN_ROWS")
    if not holdout:
        raise PITReplayError("NO_CHRONOLOGICAL_HOLDOUT_ROWS")
    # A global train count cannot qualify an unrelated sport, market or
    # frozen model version as a chronological holdout. Require prior
    # settled rows in the exact cohort evaluated by the research CLI.
    train_groups = {(r["sport"].strip().upper(), r["market"].strip().upper(),
                     r["model_version"].strip()) for r in train}
    holdout_groups = {(r["sport"].strip().upper(), r["market"].strip().upper(),
                       r["model_version"].strip()) for r in holdout}
    missing = sorted(holdout_groups - train_groups)
    if missing:
        sport, market, version = missing[0]
        raise PITReplayError(f"TRAINING_GROUP_MISSING:{sport}/{market}/{version}")
    return {
        "train": train, "holdout": holdout,
        "train_n": len(train), "holdout_n": len(holdout),
        "cutoff": cutoff.isoformat(),
        "provenance": "METADATA_ONLY_NOT_INDEPENDENTLY_AUTHENTICATED",
        "production_eligible": False,
    }
