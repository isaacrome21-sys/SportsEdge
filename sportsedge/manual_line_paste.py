"""Parse phone-pasted two-sided sportsbook lines into NFL RUN IT quotes.

This lane does not call any odds API. One-sided pastes fail closed.
Output is quotes only. It does not create Model_P, Truth Gate, or OFFICIAL.
"""
from __future__ import annotations

from datetime import datetime
import re
from typing import Any

from sportsedge.nfl_run_it import normalize_quote

SCHEMA = "SPORTSEDGE_MANUAL_LINE_PASTE_V1"
SUPPORTED_SPORTS = frozenset({"NFL", "CFB", "MLB"})
_BOOK_ALIASES = {
    "DK": "draftkings",
    "DRAFTKINGS": "draftkings",
    "FD": "fanduel",
    "FANDUEL": "fanduel",
    "MGM": "betmgm",
    "BETMGM": "betmgm",
}


class ManualLinePasteError(ValueError):
    pass


_HEADER = re.compile(
    r"^(NFL|CFB|MLB)\s+(\d{4}-\d{2}-\d{2})\s+(\S+)(?:\s+retrieved_at=(\S+))?\s*$",
    re.IGNORECASE,
)
_GAME = re.compile(r"^(\S+(?:\s+\S+)*?)\s+@\s+(\S+(?:\s+\S+)*)$")
_AMERICAN = r"([+-]?\d{3,})"
_ML = re.compile(
    rf"^(?:ML|MONEYLINE)\s+(\S+)\s+{_AMERICAN}\s*/\s*(\S+)\s+{_AMERICAN}$",
    re.IGNORECASE,
)
_SPREAD = re.compile(
    rf"^(?:SPREAD|RL|RUN_LINE)\s+(\S+)\s+([+-]?\d+(?:\.\d+)?)\s+{_AMERICAN}"
    rf"\s*/\s*(\S+)\s+([+-]?\d+(?:\.\d+)?)\s+{_AMERICAN}$",
    re.IGNORECASE,
)
_TOTAL = re.compile(
    rf"^(?:TOTAL|OU)\s+(\d+(?:\.\d+)?)\s+(OVER|O)\s+{_AMERICAN}"
    rf"\s*/\s*(UNDER|U)\s+{_AMERICAN}$",
    re.IGNORECASE,
)


def _book(raw: str) -> str:
    key = raw.strip().upper()
    if key in _BOOK_ALIASES:
        return _BOOK_ALIASES[key]
    out = raw.strip().lower()
    if not out:
        raise ManualLinePasteError("BOOK_REQUIRED")
    return out


def _aware(value: str) -> str:
    raw = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ManualLinePasteError("RETRIEVED_AT_INVALID") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ManualLinePasteError("RETRIEVED_AT_TIMEZONE_REQUIRED")
    return dt.isoformat()


def _american(value: str) -> int:
    odds = int(value)
    if -100 < odds < 100:
        raise ManualLinePasteError("AMERICAN_ODDS_INVALID")
    return odds


def parse_manual_line_paste(text: str) -> dict[str, Any]:
    if not str(text or "").strip():
        raise ManualLinePasteError("PASTE_EMPTY")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise ManualLinePasteError("PASTE_EMPTY")
    header = _HEADER.match(lines[0])
    if header is None:
        raise ManualLinePasteError("PASTE_HEADER_INVALID")
    sport = header.group(1).upper()
    slate_date = header.group(2)
    book = _book(header.group(3))
    retrieved_raw = header.group(4)
    if not retrieved_raw:
        raise ManualLinePasteError("RETRIEVED_AT_REQUIRED")
    retrieved_at = _aware(retrieved_raw)

    quotes: list[dict[str, Any]] = []
    away = home = None
    game_id = None
    for raw in lines[1:]:
        game = _GAME.match(raw)
        if game:
            away, home = game.group(1).strip(), game.group(2).strip()
            game_id = f"{slate_date}-{away}-{home}".replace(" ", "")
            continue
        if home is None or away is None or game_id is None:
            raise ManualLinePasteError("GAME_LINE_REQUIRED_BEFORE_MARKETS")
        ml = _ML.match(raw)
        if ml:
            quotes.extend(
                [
                    {
                        "game_id": game_id,
                        "home": home,
                        "away": away,
                        "market": "moneyline",
                        "selection": ml.group(1),
                        "line": None,
                        "price_american": _american(ml.group(2)),
                        "book": book,
                        "retrieved_at": retrieved_at,
                    },
                    {
                        "game_id": game_id,
                        "home": home,
                        "away": away,
                        "market": "moneyline",
                        "selection": ml.group(3),
                        "line": None,
                        "price_american": _american(ml.group(4)),
                        "book": book,
                        "retrieved_at": retrieved_at,
                    },
                ]
            )
            continue
        spread = _SPREAD.match(raw)
        if spread:
            quotes.extend(
                [
                    {
                        "game_id": game_id,
                        "home": home,
                        "away": away,
                        "market": "spread",
                        "selection": spread.group(1),
                        "line": float(spread.group(2)),
                        "price_american": _american(spread.group(3)),
                        "book": book,
                        "retrieved_at": retrieved_at,
                    },
                    {
                        "game_id": game_id,
                        "home": home,
                        "away": away,
                        "market": "spread",
                        "selection": spread.group(4),
                        "line": float(spread.group(5)),
                        "price_american": _american(spread.group(6)),
                        "book": book,
                        "retrieved_at": retrieved_at,
                    },
                ]
            )
            continue
        total = _TOTAL.match(raw)
        if total:
            quotes.extend(
                [
                    {
                        "game_id": game_id,
                        "home": home,
                        "away": away,
                        "market": "total",
                        "selection": "OVER",
                        "line": float(total.group(1)),
                        "price_american": _american(total.group(3)),
                        "book": book,
                        "retrieved_at": retrieved_at,
                    },
                    {
                        "game_id": game_id,
                        "home": home,
                        "away": away,
                        "market": "total",
                        "selection": "UNDER",
                        "line": float(total.group(1)),
                        "price_american": _american(total.group(5)),
                        "book": book,
                        "retrieved_at": retrieved_at,
                    },
                ]
            )
            continue
        raise ManualLinePasteError(f"PASTE_LINE_UNRECOGNIZED:{raw}")

    if not quotes:
        raise ManualLinePasteError("PASTE_NO_MARKETS")

    normalized = [normalize_quote(q) for q in quotes]
    for q in normalized:
        q["retrieved_at"] = q["retrieved_at"].isoformat()
    return {
        "schema": SCHEMA,
        "sport": sport,
        "book": book,
        "slate_date": slate_date,
        "source": "MANUAL",
        "odds_api": False,
        "quotes": normalized,
        "authority_footer": "NOT Model_P / NOT Truth Gate / NOT OFFICIAL",
    }


__all__ = ["ManualLinePasteError", "SCHEMA", "parse_manual_line_paste"]
