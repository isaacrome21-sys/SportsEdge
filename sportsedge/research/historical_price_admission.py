"""Fail-closed historical sportsbook snapshot admission.

Research/benchmark evidence only. Never grants Model_P, promotion, staking, or OFFICIAL authority.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping, Sequence
import math

FEATURED_MARKETS = {"h2h": "moneyline", "spreads": "spread", "totals": "game_total"}


def _utc(value: object, label: str) -> datetime:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception as exc:
        raise ValueError(f"{label} must be ISO8601") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return dt.astimezone(timezone.utc)


def _sha256(value: object, label: str) -> str:
    text = str(value or "").lower()
    if len(text) != 64 or any(c not in "0123456789abcdef" for c in text):
        raise ValueError(f"{label} must be SHA256")
    return text


def _finite_number(value: object, label: str) -> float:
    try:
        out = float(value)
    except Exception as exc:
        raise ValueError(f"{label} must be numeric") from exc
    if not math.isfinite(out):
        raise ValueError(f"{label} must be finite")
    return out


def _outcomes(snapshot: Mapping[str, object]) -> Sequence[Mapping[str, object]]:
    rows = snapshot.get("outcomes")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)) or len(rows) != 2:
        raise ValueError("exactly two outcomes required for paired benchmark admission")
    if not all(isinstance(x, Mapping) for x in rows):
        raise ValueError("outcomes must be mappings")
    return rows  # type: ignore[return-value]


def validate_historical_snapshot(snapshot: Mapping[str, object]) -> dict:
    required = (
        "sport_key",
        "event_id",
        "commence_time_utc",
        "snapshot_timestamp_utc",
        "book_key",
        "book_title",
        "book_last_update_utc",
        "market_key",
        "outcomes",
        "raw_byte_sha256",
        "retrieved_at_utc",
        "source_request_sha256",
    )
    for key in required:
        if snapshot.get(key) in (None, "", []):
            raise ValueError(f"{key} required")

    commence = _utc(snapshot["commence_time_utc"], "commence_time_utc")
    snap_ts = _utc(snapshot["snapshot_timestamp_utc"], "snapshot_timestamp_utc")
    book_update = _utc(snapshot["book_last_update_utc"], "book_last_update_utc")
    retrieved = _utc(snapshot["retrieved_at_utc"], "retrieved_at_utc")
    if snap_ts >= commence:
        raise ValueError("historical snapshot at/after commence time is not pregame evidence")
    if book_update > snap_ts:
        raise ValueError("book_last_update_utc cannot exceed snapshot_timestamp_utc")

    market_key = str(snapshot["market_key"])
    if market_key not in FEATURED_MARKETS:
        raise ValueError("unsupported historical market")
    family = FEATURED_MARKETS[market_key]

    rows = list(_outcomes(snapshot))
    names = [str(r.get("name") or "").strip() for r in rows]
    if any(not n for n in names) or len(set(names)) != 2:
        raise ValueError("paired outcomes require two distinct names")
    for idx, row in enumerate(rows):
        _finite_number(row.get("price"), f"outcomes[{idx}].price")

    if market_key == "spreads":
        points = [_finite_number(r.get("point"), f"outcomes[{i}].point") for i, r in enumerate(rows)]
        if abs(points[0] + points[1]) > 1e-9:
            raise ValueError("spread outcomes must carry matched opposite points")
    elif market_key == "totals":
        lowered = {n.lower() for n in names}
        if lowered != {"over", "under"}:
            raise ValueError("total outcomes must be Over and Under")
        points = [_finite_number(r.get("point"), f"outcomes[{i}].point") for i, r in enumerate(rows)]
        if abs(points[0] - points[1]) > 1e-9:
            raise ValueError("total outcomes must carry the same total")

    out = {
        "schema": "SPORTSEDGE_HISTORICAL_PRICE_ADMISSION_RESULT_V1",
        "admitted": True,
        "role": "REPLAY_BENCHMARK_ONLY",
        "market_family": family,
        "sport_key": str(snapshot["sport_key"]),
        "event_id": str(snapshot["event_id"]),
        "book_key": str(snapshot["book_key"]),
        "book_title": str(snapshot["book_title"]),
        "commence_time_utc": commence.isoformat().replace("+00:00", "Z"),
        "snapshot_timestamp_utc": snap_ts.isoformat().replace("+00:00", "Z"),
        "book_last_update_utc": book_update.isoformat().replace("+00:00", "Z"),
        "retrieved_at_utc": retrieved.isoformat().replace("+00:00", "Z"),
        "raw_byte_sha256": _sha256(snapshot["raw_byte_sha256"], "raw_byte_sha256"),
        "source_request_sha256": _sha256(snapshot["source_request_sha256"], "source_request_sha256"),
        "outcomes": [dict(r) for r in rows],
        "sportsbook_inputs_allowed_in_model_fit": False,
        "model_p_authority": False,
        "promotion_authority": False,
        "official_authority": False,
    }
    return out


def assert_no_market_contamination(feature_names: Sequence[str]) -> None:
    forbidden = ("odds", "price", "spread", "total", "moneyline", "handle", "ticket", "book", "market")
    contaminated = sorted({name for name in feature_names if any(tok in str(name).lower() for tok in forbidden)})
    if contaminated:
        raise ValueError(f"market contamination detected: {contaminated}")
