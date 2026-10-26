"""Research-only manifest preflight for MLB full-game capture and final receipts.

This checks *last archived pregame quote*, not the unknowable final sportsbook
quote. Passing cannot grant a counted row, verified CLV, official pick or stake.
It does not replace independent review of raw bytes or capture completeness.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from math import isfinite
import re
from typing import Any, Mapping, Sequence

from .mlb_game_capture_log import REGULAR, regime_for

MARKET_SIDES = {
    "MONEYLINE": frozenset({"HOME", "AWAY"}),
    "RUN_LINE": frozenset({"HOME", "AWAY"}),
    "TOTALS": frozenset({"OVER", "UNDER"}),
}


class MLBGameLineReceiptError(ValueError):
    pass


def _time(value: Any, reason: str) -> datetime:
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise MLBGameLineReceiptError(reason) from exc
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise MLBGameLineReceiptError(reason)
    return stamp.astimezone(timezone.utc)


def _sha(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _line(value: Any, market: str) -> float | None:
    if market == "MONEYLINE":
        if value not in (None, "ML"):
            raise MLBGameLineReceiptError("MARKET_LINE_MISMATCH")
        return None
    if isinstance(value, bool):
        raise MLBGameLineReceiptError("MARKET_LINE_INVALID")
    try:
        point = float(value)
    except (ValueError, TypeError) as exc:
        raise MLBGameLineReceiptError("MARKET_LINE_INVALID") from exc
    if not isfinite(point):
        raise MLBGameLineReceiptError("MARKET_LINE_INVALID")
    return point


def _observed_price(value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise MLBGameLineReceiptError("TWO_SIDED_PRICE_INVALID")
    if -100 < value < 100 or value == 0:
        raise MLBGameLineReceiptError("TWO_SIDED_PRICE_INVALID")


def audit_game_line_receipt_manifest(
    *,
    game_pk: int,
    official_date: str,
    season_type: str,
    start_at_utc: str,
    market: str,
    line: float | str | None,
    entry_capture_id: str,
    close_capture_id: str,
    observations: Sequence[Mapping[str, Any]],
    archive_sealed_at_utc: str,
    final: Mapping[str, Any],
) -> dict[str, Any]:
    """Require a complete-shaped immutable quote/final *manifest* for review.

    Assumes supplied manifest is exhaustive; this API cannot independently
    verify the source bytes or prove the sportsbook emitted no later quote.
    """
    if game_pk is None or isinstance(game_pk, bool) or not isinstance(game_pk, int) or game_pk <= 0:
        raise MLBGameLineReceiptError("GAME_ID_INVALID")
    try:
        date.fromisoformat(str(official_date))
    except ValueError as exc:
        raise MLBGameLineReceiptError("OFFICIAL_DATE_INVALID") from exc
    if regime_for(official_date=official_date, season_type=season_type) != REGULAR:
        raise MLBGameLineReceiptError("POSTSEASON_SHAPED_SEPARATELY")
    game_start = _time(start_at_utc, "START_TIMESTAMP_INVALID")
    sealed = _time(archive_sealed_at_utc, "ARCHIVE_SEAL_TIMESTAMP_INVALID")
    if sealed < game_start:
        raise MLBGameLineReceiptError("ARCHIVE_NOT_SEALED_AFTER_START")
    market = str(market).upper()
    if market not in MARKET_SIDES:
        raise MLBGameLineReceiptError("GAME_LINE_MARKET_NOT_FROZEN")
    canonical_line = _line(line, market)
    if not entry_capture_id or not close_capture_id or entry_capture_id == close_capture_id:
        raise MLBGameLineReceiptError("ENTRY_AND_CLOSE_NOT_DISTINCT")
    if not isinstance(observations, Sequence) or isinstance(observations, (str, bytes)):
        raise MLBGameLineReceiptError("OBSERVATIONS_INVALID")

    snapshots: dict[str, tuple[datetime, Mapping[str, Any]]] = {}
    for row in observations:
        if not isinstance(row, Mapping):
            raise MLBGameLineReceiptError("OBSERVATIONS_INVALID")
        identity = str(row.get("capture_id") or "")
        if not identity or identity in snapshots:
            raise MLBGameLineReceiptError("DUPLICATE_OR_MISSING_CAPTURE_ID")
        if row.get("game_pk") != game_pk or str(row.get("market") or "").upper() != market:
            raise MLBGameLineReceiptError("CAPTURE_CONTRACT_MISMATCH")
        if str(row.get("book") or "").upper() != "DRAFTKINGS":
            raise MLBGameLineReceiptError("CAPTURE_BOOK_MISMATCH")
        if _line(row.get("line"), market) != canonical_line:
            raise MLBGameLineReceiptError("CAPTURE_CONTRACT_MISMATCH")
        if not _sha(row.get("raw_sha256")):
            raise MLBGameLineReceiptError("CAPTURE_RAW_SHA_MISSING")
        prices = row.get("prices")
        if not isinstance(prices, Mapping) or set(prices) != MARKET_SIDES[market]:
            raise MLBGameLineReceiptError("TWO_SIDED_QUOTE_MISSING")
        for price in prices.values():
            _observed_price(price)
        captured = _time(row.get("captured_at_utc"), "QUOTE_TIMESTAMP_INVALID")
        if captured > sealed:
            raise MLBGameLineReceiptError("ARCHIVE_SEALED_BEFORE_QUOTE")
        snapshots[identity] = (captured, row)
    if entry_capture_id not in snapshots or close_capture_id not in snapshots:
        raise MLBGameLineReceiptError("ENTRY_OR_CLOSE_NOT_ARCHIVED")
    entry_at = snapshots[entry_capture_id][0]
    close_at = snapshots[close_capture_id][0]
    if not (entry_at < close_at < game_start):
        raise MLBGameLineReceiptError("ENTRY_CLOSE_ORDER_INVALID")
    if (game_start - close_at).total_seconds() > 60 * 60:
        raise MLBGameLineReceiptError("CLOSE_OUTSIDE_PRESTART_WINDOW")
    pregame = [(stamp, identity) for identity, (stamp, _) in snapshots.items() if stamp < game_start]
    last_time = max(stamp for stamp, _ in pregame)
    last_ids = [identity for stamp, identity in pregame if stamp == last_time]
    if last_ids != [close_capture_id]:
        raise MLBGameLineReceiptError("CLOSE_NOT_UNIQUELY_LAST_ARCHIVED_QUOTE")

    if not isinstance(final, Mapping) or final.get("game_pk") != game_pk:
        raise MLBGameLineReceiptError("FINAL_GAME_ID_MISMATCH")
    if final.get("source") != "MLB_STATSAPI_FINAL" or final.get("status") != "FINAL":
        raise MLBGameLineReceiptError("OFFICIAL_FINAL_NOT_CAPTURED")
    if not _sha(final.get("raw_sha256")):
        raise MLBGameLineReceiptError("FINAL_RAW_SHA_MISSING")
    final_at = _time(final.get("captured_at_utc"), "FINAL_TIMESTAMP_INVALID")
    if final_at <= game_start:
        raise MLBGameLineReceiptError("FINAL_NOT_POSTSTART")
    scores = []
    for key in ("away_score", "home_score"):
        value = final.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise MLBGameLineReceiptError("FINAL_SCORE_INVALID")
        scores.append(value)
    if scores[0] == scores[1]:
        raise MLBGameLineReceiptError("FINAL_TIE_UNRESOLVED")

    return {
        "status": "MANIFEST_SHAPED_RESEARCH_ONLY",
        "game_pk": game_pk,
        "market": market,
        "close_capture_id": close_capture_id,
        "last_archived_pregame_quote": True,
        "final_receipt_present": True,
        "actual_last_book_quote_proven": False,
        "archive_completeness_independently_verified": False,
        "counted": False,
        "verified_clv": False,
        "promotion_authority": False,
    }
