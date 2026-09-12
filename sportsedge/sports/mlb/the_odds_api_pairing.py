"""Pair immutable The Odds API MLB historical snapshots for replay-readiness audit.

This module is evidence plumbing only. It never creates Model_P, changes market
eligibility, sets an edge floor, or grants promotion/Truth Gate authority.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

from .paired_replay_readiness import audit_paired_replay_readiness

ARCHIVE_SCHEMA = "MLB_THE_ODDS_API_HISTORICAL_ARCHIVE_V1"
SOURCE = "THE_ODDS_API_HISTORICAL"
PROVENANCE = "the_odds_api_historical_provider_snapshot"


class MLBTheOddsAPIPairingError(ValueError):
    pass


def _read_snapshot(directory: Path) -> tuple[dict[str, Any], dict[str, Any], str]:
    raw_path = directory / "snapshot.json"
    meta_path = directory / "snapshot.meta.json"
    try:
        raw = raw_path.read_bytes()
        payload = json.loads(raw)
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MLBTheOddsAPIPairingError("MLB_TODDS_SNAPSHOT_UNREADABLE") from exc
    if not isinstance(payload, dict) or not isinstance(meta, dict):
        raise MLBTheOddsAPIPairingError("MLB_TODDS_SNAPSHOT_MAPPING_REQUIRED")
    digest = sha256(raw).hexdigest()
    if meta.get("schema") != ARCHIVE_SCHEMA or meta.get("source") != SOURCE:
        raise MLBTheOddsAPIPairingError("MLB_TODDS_ARCHIVE_IDENTITY_INVALID")
    if meta.get("payload_sha256") != digest:
        raise MLBTheOddsAPIPairingError("MLB_TODDS_ARCHIVE_SHA256_MISMATCH")
    if payload.get("timestamp") != meta.get("provider_timestamp"):
        raise MLBTheOddsAPIPairingError("MLB_TODDS_PROVIDER_TIMESTAMP_MISMATCH")
    if meta.get("interpolated") is not False or meta.get("reconstructed") is not False:
        raise MLBTheOddsAPIPairingError("MLB_TODDS_RECONSTRUCTED_ARCHIVE_FORBIDDEN")
    if not isinstance(payload.get("data"), list):
        raise MLBTheOddsAPIPairingError("MLB_TODDS_DATA_LIST_REQUIRED")
    return payload, meta, digest


def _selection_key(outcome: Mapping[str, Any]) -> str:
    name = str(outcome.get("name") or "").strip()
    if not name:
        raise MLBTheOddsAPIPairingError("MLB_TODDS_OUTCOME_NAME_REQUIRED")
    point = outcome.get("point")
    return name if point is None else f"{name}|point={point}"


def _index(payload: Mapping[str, Any], *, source_sha256: str) -> tuple[dict[tuple[str, str, str, str], dict[str, Any]], list[str]]:
    index: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    errors: list[str] = []
    observed_at = payload.get("timestamp")
    for event in payload.get("data", []):
        if not isinstance(event, Mapping):
            errors.append("EVENT_MAPPING_REQUIRED")
            continue
        event_id = str(event.get("id") or "").strip()
        event_start = event.get("commence_time")
        if not event_id or not event_start:
            errors.append("EVENT_ID_OR_START_MISSING")
            continue
        books = event.get("bookmakers")
        if not isinstance(books, list):
            continue
        for book in books:
            if not isinstance(book, Mapping):
                continue
            book_key = str(book.get("key") or "").strip()
            markets = book.get("markets")
            if not book_key or not isinstance(markets, list):
                continue
            for market in markets:
                if not isinstance(market, Mapping):
                    continue
                market_key = str(market.get("key") or "").strip()
                outcomes = market.get("outcomes")
                if market_key not in {"h2h", "spreads", "totals"} or not isinstance(outcomes, list):
                    continue
                for outcome in outcomes:
                    if not isinstance(outcome, Mapping):
                        continue
                    try:
                        selection = _selection_key(outcome)
                    except MLBTheOddsAPIPairingError as exc:
                        errors.append(str(exc))
                        continue
                    identity = (event_id, market_key, selection, book_key)
                    if identity in index:
                        errors.append(f"DUPLICATE_IDENTITY:{'|'.join(identity)}")
                        continue
                    index[identity] = {
                        "event_start": event_start,
                        "observed_at": observed_at,
                        "price": outcome.get("price"),
                        "source_sha256": source_sha256,
                    }
    return index, errors


def audit_snapshot_pair(decision_dir: Path, close_dir: Path) -> dict[str, Any]:
    """Build exact same-threshold decision/close pairs from two provider snapshots."""
    decision_payload, decision_meta, decision_sha = _read_snapshot(decision_dir)
    close_payload, close_meta, close_sha = _read_snapshot(close_dir)
    decision_index, decision_errors = _index(decision_payload, source_sha256=decision_sha)
    close_index, close_errors = _index(close_payload, source_sha256=close_sha)

    pairs: list[dict[str, Any]] = []
    for identity in sorted(set(decision_index) & set(close_index)):
        d = decision_index[identity]
        c = close_index[identity]
        if d["event_start"] != c["event_start"]:
            continue
        event_id, market, selection, book = identity
        common = {
            "event_id": event_id,
            "market": market,
            "selection": selection,
            "book": book,
            "provenance": PROVENANCE,
        }
        pairs.append({
            "event_start": d["event_start"],
            "decision": {**common, "observed_at": d["observed_at"], "price": d["price"], "source_sha256": d["source_sha256"]},
            "close": {**common, "observed_at": c["observed_at"], "price": c["price"], "source_sha256": c["source_sha256"]},
        })

    result = audit_paired_replay_readiness(pairs)
    source_errors = decision_errors + close_errors
    if source_errors:
        result["status"] = "BLOCKED_PAIRED_MARKET_EVIDENCE"
    result.update({
        "adapter": "MLB_THE_ODDS_API_PAIRED_REPLAY_V1",
        "decision_requested_at": decision_meta.get("requested_at"),
        "decision_provider_timestamp": decision_meta.get("provider_timestamp"),
        "decision_source_sha256": decision_sha,
        "close_requested_at": close_meta.get("requested_at"),
        "close_provider_timestamp": close_meta.get("provider_timestamp"),
        "close_source_sha256": close_sha,
        "candidate_identity_count": len(set(decision_index) & set(close_index)),
        "source_errors": source_errors,
        "promotion_authority": False,
        "may_change_market_eligibility": False,
    })
    return result
