"""Strict manual CFB game-market quote ingestion for HYBRID RUN IT.

Manual quote files are market inputs only. They never create Model_P. The parser
requires paired DraftKings prices and an aware pregame observation timestamp; the
canonical run machine separately proves the timestamp precedes the fetched kickoff.
"""
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
from typing import Any, Mapping

from .source import CFBQuote

SCHEMA = "CFB_MANUAL_QUOTES_V1"
BOOK_KEY = "draftkings"
_MARKETS = {"MONEYLINE", "SPREAD", "TOTAL"}
_SIDES = {"MONEYLINE": {"HOME", "AWAY"}, "SPREAD": {"HOME", "AWAY"}, "TOTAL": {"OVER", "UNDER"}}


class CFBManualQuoteError(ValueError):
    pass


def _aware(value: Any) -> str:
    raw = str(value or "").strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise CFBManualQuoteError("CFB_MANUAL_QUOTES_OBSERVED_AT_INVALID") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise CFBManualQuoteError("CFB_MANUAL_QUOTES_OBSERVED_AT_TIMEZONE_REQUIRED")
    return dt.isoformat()


def _num(value: Any, code: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise CFBManualQuoteError(code) from exc
    if not isfinite(out):
        raise CFBManualQuoteError(code)
    return out


def _offer(game_id: str, market: str, side: str, line: float, odds: float, observed: str) -> str:
    raw = f"MANUAL|{BOOK_KEY}|{game_id}|{market}|{side}|{line!r}|{odds!r}|{observed}".encode()
    return sha256(raw).hexdigest()


def load_manual_cfb_quotes(path: str | Path) -> list[CFBQuote]:
    p = Path(path)
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CFBManualQuoteError("CFB_MANUAL_QUOTES_FILE_INVALID") from exc
    if not isinstance(payload, Mapping) or payload.get("schema_version") != SCHEMA:
        raise CFBManualQuoteError("CFB_MANUAL_QUOTES_SCHEMA_INVALID")
    if str(payload.get("book_key") or "").strip().lower() != BOOK_KEY:
        raise CFBManualQuoteError("CFB_MANUAL_QUOTES_BOOK_MUST_BE_DRAFTKINGS")
    observed = _aware(payload.get("observed_at"))
    rows = payload.get("quotes")
    if not isinstance(rows, list) or not rows:
        raise CFBManualQuoteError("CFB_MANUAL_QUOTES_EMPTY")
    quotes: list[CFBQuote] = []
    groups: dict[tuple[str, str, float], list[tuple[str, float]]] = {}
    for index, raw in enumerate(rows):
        if not isinstance(raw, Mapping):
            raise CFBManualQuoteError(f"CFB_MANUAL_QUOTE_ROW_INVALID:{index}")
        game_id = str(raw.get("game_id") or "").strip()
        market = str(raw.get("market") or "").strip().upper()
        side = str(raw.get("side") or "").strip().upper()
        if not game_id:
            raise CFBManualQuoteError(f"CFB_MANUAL_QUOTE_GAME_ID_MISSING:{index}")
        if market not in _MARKETS or side not in _SIDES.get(market, set()):
            raise CFBManualQuoteError(f"CFB_MANUAL_QUOTE_MARKET_SIDE_INVALID:{index}")
        line = _num(raw.get("line", 0.0), f"CFB_MANUAL_QUOTE_LINE_INVALID:{index}")
        if market == "MONEYLINE" and abs(line) > 1e-12:
            raise CFBManualQuoteError(f"CFB_MANUAL_MONEYLINE_LINE_MUST_BE_ZERO:{index}")
        odds = _num(raw.get("american_odds"), f"CFB_MANUAL_QUOTE_ODDS_INVALID:{index}")
        if -100.0 < odds < 100.0:
            raise CFBManualQuoteError(f"CFB_MANUAL_QUOTE_ODDS_INVALID:{index}")
        groups.setdefault((game_id, market, line), []).append((side, odds))
        quotes.append(CFBQuote(game_id=game_id, period="FG", market=market, entity_id=game_id,
            side=side, line=line, american_odds=odds, book_key=BOOK_KEY, sportsbook="DraftKings",
            retrieved_at=observed, offer_id=_offer(game_id, market, side, line, odds, observed), is_alternate=False))
    for (game_id, market, line), pair in groups.items():
        sides = [side for side, _ in pair]
        if len(pair) != 2 or set(sides) != _SIDES[market] or len(set(sides)) != 2:
            raise CFBManualQuoteError(f"CFB_MANUAL_QUOTES_TWO_SIDED_PAIR_REQUIRED:{game_id}:{market}:{line}")
    return quotes


__all__ = ["BOOK_KEY", "CFBManualQuoteError", "SCHEMA", "load_manual_cfb_quotes"]
