"""Immutable receipt validation for the closed fresh evidence window.

A complete receipt bundle proves only that the preregistered inputs exist with
coherent identity and point-in-time ordering.  It never opens or scores the
window and grants no production authority.
"""

from __future__ import annotations

from datetime import datetime
import re
from typing import Any, Iterable, Mapping

from sportsedge.research_surface_guard import (
    SPENT_SEASON,
    SPENT_WINDOW_ID,
    ResearchSurfaceError,
)

WINDOW_ID = "FRESH_PROP_TEAM_TOTAL_WINDOW_V1"
MINIMUM_SEASON = 2026
REQUIRED_KINDS = (
    "pit_feature_snapshot",
    "paired_pregame_quotes",
    "same_book_pregame_close",
    "settlement",
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")


def _timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ResearchSurfaceError(f"FRESH_RECEIPT_TIMESTAMP_REQUIRED:{field}")
    raw = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ResearchSurfaceError(f"FRESH_RECEIPT_TIMESTAMP_INVALID:{field}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ResearchSurfaceError(f"FRESH_RECEIPT_TIMESTAMP_TZ_REQUIRED:{field}")
    return parsed


def _common_identity(receipt: Mapping[str, Any], kind: str) -> tuple[int, str, str, str]:
    if receipt.get("window_id") == SPENT_WINDOW_ID:
        raise ResearchSurfaceError("SPENT_TECHNICAL_FAILURE: spent 2025 window receipt forbidden")
    if receipt.get("window_id") != WINDOW_ID:
        raise ResearchSurfaceError(f"FRESH_RECEIPT_WINDOW_ID_MISMATCH:{kind}")

    season = receipt.get("season")
    if isinstance(season, bool) or not isinstance(season, int):
        raise ResearchSurfaceError(f"FRESH_RECEIPT_SEASON_INVALID:{kind}")
    if season == SPENT_SEASON or season < MINIMUM_SEASON:
        raise ResearchSurfaceError(f"FRESH_RECEIPT_SEASON_FORBIDDEN:{season}")

    game_id = str(receipt.get("game_id") or "").strip()
    market_id = str(receipt.get("market_id") or "").strip()
    if not game_id:
        raise ResearchSurfaceError(f"FRESH_RECEIPT_GAME_ID_REQUIRED:{kind}")
    if not market_id:
        raise ResearchSurfaceError(f"FRESH_RECEIPT_MARKET_ID_REQUIRED:{kind}")

    content_sha = str(receipt.get("content_sha256") or "").strip().lower()
    if not _SHA256.fullmatch(content_sha):
        raise ResearchSurfaceError(f"FRESH_RECEIPT_CONTENT_SHA256_INVALID:{kind}")

    code_sha = str(receipt.get("candidate_code_sha") or "").strip().lower()
    if not _GIT_SHA.fullmatch(code_sha):
        raise ResearchSurfaceError(f"FRESH_RECEIPT_CODE_SHA_INVALID:{kind}")

    return season, game_id, market_id, code_sha


def validate_fresh_window_source_receipts(
    receipts: Iterable[Mapping[str, Any]] | None,
) -> dict[str, Any]:
    """Validate one game/market receipt bundle while keeping the window closed.

    Missing receipt kinds are a normal collection state and return a closed
    report. Present-but-invalid receipts fail closed with ResearchSurfaceError.
    A complete valid set returns COMPLETE_RECEIPTS_WINDOW_STILL_CLOSED and
    explicitly leaves scoring/promotion/open authority false.
    """
    rows = [dict(row) for row in (receipts or [])]
    by_kind: dict[str, dict[str, Any]] = {}
    for row in rows:
        kind = str(row.get("kind") or "").strip()
        if kind not in REQUIRED_KINDS:
            raise ResearchSurfaceError(f"FRESH_RECEIPT_KIND_UNSUPPORTED:{kind or 'EMPTY'}")
        if kind in by_kind:
            raise ResearchSurfaceError(f"FRESH_RECEIPT_DUPLICATE_KIND:{kind}")
        by_kind[kind] = row

    missing = [kind for kind in REQUIRED_KINDS if kind not in by_kind]
    if missing:
        return {
            "schema_version": "FRESH_WINDOW_SOURCE_RECEIPT_REPORT_V1",
            "window_id": WINDOW_ID,
            "state": "CLOSED_MISSING_RECEIPTS",
            "missing_receipts": missing,
            "complete_receipts": False,
            "ready_for_open_review": False,
            "scoring_allowed": False,
            "promotion_allowed": False,
            "automatic_open_allowed": False,
        }

    identities = {
        kind: _common_identity(row, kind)
        for kind, row in by_kind.items()
    }
    first = identities[REQUIRED_KINDS[0]]
    if any(identity != first for identity in identities.values()):
        raise ResearchSurfaceError("FRESH_RECEIPT_IDENTITY_MISMATCH")

    feature = by_kind["pit_feature_snapshot"]
    quote = by_kind["paired_pregame_quotes"]
    close = by_kind["same_book_pregame_close"]
    settlement = by_kind["settlement"]

    feature_at = _timestamp(feature.get("observed_at"), "pit_feature_snapshot.observed_at")
    quote_at = _timestamp(quote.get("observed_at"), "paired_pregame_quotes.observed_at")
    decision_at = _timestamp(quote.get("decision_at"), "paired_pregame_quotes.decision_at")
    close_at = _timestamp(close.get("observed_at"), "same_book_pregame_close.observed_at")
    start_at = _timestamp(quote.get("event_start_at"), "paired_pregame_quotes.event_start_at")
    close_start_at = _timestamp(close.get("event_start_at"), "same_book_pregame_close.event_start_at")
    settlement_start_at = _timestamp(settlement.get("event_start_at"), "settlement.event_start_at")
    settled_at = _timestamp(settlement.get("observed_at"), "settlement.observed_at")

    if not (feature_at < quote_at <= decision_at < close_at < start_at < settled_at):
        raise ResearchSurfaceError("FRESH_RECEIPT_TEMPORAL_ORDER_INVALID")
    if close_start_at != start_at or settlement_start_at != start_at:
        raise ResearchSurfaceError("FRESH_RECEIPT_EVENT_START_MISMATCH")

    quote_book = str(quote.get("book") or "").strip().lower()
    close_book = str(close.get("book") or "").strip().lower()
    if not quote_book or not close_book or quote_book != close_book:
        raise ResearchSurfaceError("FRESH_RECEIPT_SAME_BOOK_CLOSE_REQUIRED")

    if quote.get("paired") is not True:
        raise ResearchSurfaceError("FRESH_RECEIPT_PAIRED_QUOTES_REQUIRED")
    sides = quote.get("sides")
    if not isinstance(sides, list) or len(sides) != 2:
        raise ResearchSurfaceError("FRESH_RECEIPT_TWO_SIDED_PAIR_REQUIRED")
    normalized_sides = {str(side).strip().upper() for side in sides}
    if len(normalized_sides) != 2 or "" in normalized_sides:
        raise ResearchSurfaceError("FRESH_RECEIPT_TWO_SIDED_PAIR_INVALID")

    season, game_id, market_id, code_sha = first
    return {
        "schema_version": "FRESH_WINDOW_SOURCE_RECEIPT_REPORT_V1",
        "window_id": WINDOW_ID,
        "season": season,
        "game_id": game_id,
        "market_id": market_id,
        "candidate_code_sha": code_sha,
        "book": quote_book,
        "state": "COMPLETE_RECEIPTS_WINDOW_STILL_CLOSED",
        "missing_receipts": [],
        "complete_receipts": True,
        "ready_for_open_review": True,
        "scoring_allowed": False,
        "promotion_allowed": False,
        "automatic_open_allowed": False,
    }


__all__ = ["REQUIRED_KINDS", "WINDOW_ID", "validate_fresh_window_source_receipts"]
