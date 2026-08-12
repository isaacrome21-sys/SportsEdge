"""Exact-book, exact-market closing-line matching for SportsEdge audit data."""
from __future__ import annotations

from typing import Any, Mapping, Sequence


class CLVCaptureError(ValueError):
    pass


def _identity(row: Mapping[str, Any]) -> tuple[str, str, str, str, Any, str]:
    return (
        str(row.get("book_key") or ""),
        str(row.get("game_id") or ""),
        str(row.get("market") or ""),
        str(row.get("entity_id") or ""),
        row.get("line"),
        str(row.get("side") or ""),
    )


def capture_closing_line(decision: Mapping[str, Any], closing_quotes: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    wanted = _identity(decision)
    if not all((wanted[0], wanted[1], wanted[2], wanted[5])):
        raise CLVCaptureError("DECISION_IDENTITY_INCOMPLETE")
    exact = [dict(q) for q in closing_quotes if _identity(q) == wanted]
    if len(exact) == 0:
        return {
            "status": "NO_CLOSING_LINE",
            "wager_key": decision.get("wager_key"),
            "book_key": wanted[0],
            "game_id": wanted[1],
            "market": wanted[2],
            "entity_id": wanted[3],
            "line": wanted[4],
            "side": wanted[5],
        }
    if len(exact) > 1:
        raise CLVCaptureError("AMBIGUOUS_EXACT_CLOSING_LINE")
    q = exact[0]
    return {
        "status": "MATCHED",
        "wager_key": decision.get("wager_key"),
        "book_key": wanted[0],
        "game_id": wanted[1],
        "market": wanted[2],
        "entity_id": wanted[3],
        "line": wanted[4],
        "side": wanted[5],
        "bet_odds": decision.get("american_odds"),
        "closing_odds": q.get("american_odds"),
        "closing_retrieved_at": q.get("retrieved_at"),
    }
