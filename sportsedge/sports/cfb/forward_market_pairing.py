"""Fail-closed pairing for immutable CFB forward DraftKings market snapshots.

This module may establish that exact decision/close market evidence exists for a
specific event/book/market/original threshold. It cannot create Model_P, promote
a model/market, set an edge floor, grant Truth Gate PASS, staking, or OFFICIAL
status.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

SNAPSHOT_SCHEMA = "SPORTSEDGE_CFB_FORWARD_MARKET_SNAPSHOT_V1"
PAIR_SCHEMA = "SPORTSEDGE_CFB_FORWARD_MARKET_PAIR_V1"
DECISION_MIN_LEAD_MINUTES = 45.0
DECISION_MAX_LEAD_MINUTES = 120.0
CLOSE_MIN_LEAD_MINUTES = 2.0
CLOSE_MAX_LEAD_MINUTES = 20.0


class CFBForwardMarketPairingError(ValueError):
    pass


def _require(ok: bool, code: str) -> None:
    if not ok:
        raise CFBForwardMarketPairingError(code)


def _ts(value: Any, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise CFBForwardMarketPairingError(f"CFB_FORWARD_PAIR_TIMESTAMP_INVALID:{field}") from exc
    _require(parsed.tzinfo is not None and parsed.utcoffset() is not None, f"CFB_FORWARD_PAIR_TIMESTAMP_TZ_REQUIRED:{field}")
    return parsed.astimezone(timezone.utc)


def _sha(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def _read_snapshot(directory: Path) -> tuple[list[dict[str, Any]], dict[str, Any], bytes]:
    raw_path = directory / "snapshot.json"
    meta_path = directory / "snapshot.meta.json"
    try:
        raw = raw_path.read_bytes()
        payload = json.loads(raw)
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CFBForwardMarketPairingError("CFB_FORWARD_PAIR_SNAPSHOT_UNREADABLE") from exc
    _require(isinstance(payload, list), "CFB_FORWARD_PAIR_PAYLOAD_LIST_REQUIRED")
    _require(isinstance(meta, dict), "CFB_FORWARD_PAIR_META_OBJECT_REQUIRED")
    _require(meta.get("schema") == SNAPSHOT_SCHEMA, "CFB_FORWARD_PAIR_SNAPSHOT_SCHEMA_INVALID")
    _require(meta.get("source") == "THE_ODDS_API_CURRENT", "CFB_FORWARD_PAIR_SOURCE_INVALID")
    _require(str(meta.get("bookmaker") or "").lower() == "draftkings", "CFB_FORWARD_PAIR_BOOK_INVALID")
    digest = _sha(raw)
    _require(str(meta.get("payload_sha256") or "").lower() == digest, "CFB_FORWARD_PAIR_PAYLOAD_SHA_MISMATCH")
    _require(meta.get("forward_only") is True, "CFB_FORWARD_PAIR_FORWARD_ONLY_REQUIRED")
    _require(meta.get("retroactive_point_in_time_claim") is False, "CFB_FORWARD_PAIR_RETROACTIVE_CLAIM_FORBIDDEN")
    _require(meta.get("promotion_authority") is False, "CFB_FORWARD_PAIR_PROMOTION_AUTHORITY_FORBIDDEN")
    _require(meta.get("model_p_created") is False, "CFB_FORWARD_PAIR_MODEL_P_AUTHORITY_FORBIDDEN")
    _require(meta.get("eligibility_changed") is False, "CFB_FORWARD_PAIR_ELIGIBILITY_CHANGE_FORBIDDEN")
    _require(meta.get("paired_market_evidence") is False, "CFB_FORWARD_PAIR_PREDECLARED_PAIRING_FORBIDDEN")
    return [dict(x) for x in payload if isinstance(x, Mapping)], meta, raw


def _group_threshold(market: str, outcomes: list[Mapping[str, Any]]) -> str:
    if market == "h2h":
        return "NONE"
    points = []
    for outcome in outcomes:
        point = outcome.get("point")
        _require(isinstance(point, (int, float)) and not isinstance(point, bool), f"CFB_FORWARD_PAIR_POINT_REQUIRED:{market}")
        points.append(float(point))
    if market == "totals":
        unique = {round(x, 10) for x in points}
        _require(len(unique) == 1, "CFB_FORWARD_PAIR_TOTAL_THRESHOLD_INCONSISTENT")
        return f"{next(iter(unique)):g}"
    # Spread outcomes normally carry opposite signed points. Bind the market to
    # the absolute original threshold so HOME -3.5 / AWAY +3.5 form one group.
    unique = {round(abs(x), 10) for x in points}
    _require(len(unique) == 1, "CFB_FORWARD_PAIR_SPREAD_THRESHOLD_INCONSISTENT")
    return f"{next(iter(unique)):g}"


def _market_index(payload: list[dict[str, Any]]) -> dict[tuple[str, str, str, str], dict[str, Any]]:
    index: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for event in payload:
        event_id = str(event.get("id") or "").strip()
        start = event.get("commence_time")
        if not event_id or start is None:
            continue
        event_start = _ts(start, "commence_time")
        books = event.get("bookmakers")
        if not isinstance(books, list):
            continue
        for book in books:
            if not isinstance(book, Mapping) or str(book.get("key") or "").lower() != "draftkings":
                continue
            markets = book.get("markets")
            if not isinstance(markets, list):
                continue
            for market in markets:
                if not isinstance(market, Mapping):
                    continue
                market_key = str(market.get("key") or "").lower()
                if market_key not in {"h2h", "spreads", "totals"}:
                    continue
                outcomes_raw = market.get("outcomes")
                _require(isinstance(outcomes_raw, list) and len(outcomes_raw) == 2, f"CFB_FORWARD_PAIR_TWO_SIDED_MARKET_REQUIRED:{market_key}")
                outcomes = [x for x in outcomes_raw if isinstance(x, Mapping)]
                _require(len(outcomes) == 2, f"CFB_FORWARD_PAIR_OUTCOME_MAPPING_REQUIRED:{market_key}")
                threshold = _group_threshold(market_key, outcomes)
                key = (event_id, "draftkings", market_key, threshold)
                _require(key not in index, "CFB_FORWARD_PAIR_DUPLICATE_MARKET_IDENTITY")
                normalized = []
                for outcome in outcomes:
                    name = str(outcome.get("name") or "").strip()
                    price = outcome.get("price")
                    _require(bool(name), "CFB_FORWARD_PAIR_OUTCOME_NAME_REQUIRED")
                    _require(isinstance(price, (int, float)) and not isinstance(price, bool), "CFB_FORWARD_PAIR_PRICE_REQUIRED")
                    normalized.append({
                        "name": name,
                        "price": float(price),
                        "point": outcome.get("point"),
                    })
                _require(len({x["name"] for x in normalized}) == 2, "CFB_FORWARD_PAIR_OUTCOME_NAMES_NOT_DISTINCT")
                index[key] = {
                    "event_start": event_start,
                    "outcomes": sorted(normalized, key=lambda x: x["name"]),
                }
    return index


def pair_snapshots(decision_dir: Path, close_dir: Path) -> dict[str, Any]:
    decision_payload, decision_meta, decision_raw = _read_snapshot(decision_dir)
    close_payload, close_meta, close_raw = _read_snapshot(close_dir)
    decision_at = _ts(decision_meta.get("captured_at_utc"), "decision.captured_at_utc")
    close_at = _ts(close_meta.get("captured_at_utc"), "close.captured_at_utc")
    _require(decision_at < close_at, "CFB_FORWARD_PAIR_TEMPORAL_ORDER_INVALID")

    decision_index = _market_index(decision_payload)
    close_index = _market_index(close_payload)
    paired: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for key in sorted(set(decision_index) & set(close_index)):
        d = decision_index[key]
        c = close_index[key]
        event_id, book, market, threshold = key
        if d["event_start"] != c["event_start"]:
            rejected.append({"identity": list(key), "reason": "EVENT_START_CHANGED"})
            continue
        event_start = d["event_start"]
        decision_lead = (event_start - decision_at).total_seconds() / 60.0
        close_lead = (event_start - close_at).total_seconds() / 60.0
        if not (DECISION_MIN_LEAD_MINUTES <= decision_lead <= DECISION_MAX_LEAD_MINUTES):
            rejected.append({"identity": list(key), "reason": "DECISION_OUTSIDE_FROZEN_WINDOW"})
            continue
        if not (CLOSE_MIN_LEAD_MINUTES <= close_lead <= CLOSE_MAX_LEAD_MINUTES):
            rejected.append({"identity": list(key), "reason": "CLOSE_OUTSIDE_FROZEN_WINDOW"})
            continue
        if [x["name"] for x in d["outcomes"]] != [x["name"] for x in c["outcomes"]]:
            rejected.append({"identity": list(key), "reason": "OUTCOME_IDENTITY_CHANGED"})
            continue
        pair = {
            "schema": PAIR_SCHEMA,
            "event_id": event_id,
            "book": book,
            "market": market,
            "original_threshold": threshold,
            "event_start_utc": event_start.isoformat(),
            "decision_captured_at_utc": decision_at.isoformat(),
            "close_captured_at_utc": close_at.isoformat(),
            "decision_lead_minutes": decision_lead,
            "close_lead_minutes": close_lead,
            "decision_source_sha256": _sha(decision_raw),
            "close_source_sha256": _sha(close_raw),
            "decision_outcomes": d["outcomes"],
            "close_outcomes": c["outcomes"],
        }
        canonical = json.dumps(pair, sort_keys=True, separators=(",", ":")).encode("utf-8")
        pair["pair_sha256"] = sha256(canonical).hexdigest()
        paired.append(pair)

    threshold_drift_count = len(set(decision_index) - set(close_index)) + len(set(close_index) - set(decision_index))
    return {
        "contract": "SPORTSEDGE_CFB_FORWARD_MARKET_PAIRING_REPORT_V1",
        "status": "PAIRED_FORWARD_MARKET_EVIDENCE_AVAILABLE" if paired else "BLOCKED_PAIRED_MARKET_EVIDENCE",
        "paired_market_evidence": bool(paired),
        "valid_market_pair_count": len(paired),
        "rejected_common_market_count": len(rejected),
        "unmatched_or_threshold_drift_market_count": threshold_drift_count,
        "pairs": paired,
        "rejections": rejected,
        "decision_source_sha256": _sha(decision_raw),
        "close_source_sha256": _sha(close_raw),
        "model_p_created": False,
        "promotion_authority": False,
        "eligibility_changed": False,
        "truth_gate_ready": False,
        "truth_gate_pass_granted": False,
        "official_status_granted": False,
    }
