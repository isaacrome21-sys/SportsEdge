"""Forward PIT capture ledger for MLB context-model training evidence.

Creates immutable, price-blind training rows from the same public pregame
context bundle used by serving. It intentionally does not backfill context.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any, Mapping

from .mlb_context_model_features import context_model_features

CAPTURE_VERSION = "mlb_context_forward_capture_v1"


def _utc(value: str, *, field: str) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError(f"{field} required")
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def capture_training_row(
    bundle: Mapping[str, Any],
    *,
    game_date: str,
    first_pitch_utc: str,
    captured_at_utc: str,
) -> dict[str, Any]:
    first_pitch = _utc(first_pitch_utc, field="first_pitch_utc")
    captured_at = _utc(captured_at_utc, field="captured_at_utc")
    if not game_date:
        raise ValueError("game_date required")
    if captured_at >= first_pitch:
        raise ValueError("context capture must be strictly pregame")

    model = context_model_features(bundle)
    row = {
        "capture_version": CAPTURE_VERSION,
        "game_pk": bundle.get("game_pk"),
        "game_date": str(game_date),
        "first_pitch_utc": first_pitch.isoformat(),
        "captured_at_utc": captured_at.isoformat(),
        "pit_strict": True,
        "contains_sportsbook_prices": False,
        "feature_schema_version": model["schema_version"],
        "feature_sha256": model["feature_sha256"],
        "source_public_payload_sha256": model["source_public_payload_sha256"],
        "features": model["features"],
        "eligibility": model["eligibility"],
    }
    raw = json.dumps(
        row, sort_keys=True, separators=(",", ":"), default=str
    ).encode()
    row["capture_sha256"] = sha256(raw).hexdigest()
    return row
