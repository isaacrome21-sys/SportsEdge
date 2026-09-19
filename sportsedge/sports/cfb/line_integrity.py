"""Fail-closed CFB quote pair integrity.

Validates already-captured full-game quotes. Does not fetch, does not price,
and does not create Model_P / Truth Gate / OFFICIAL authority.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Mapping

AUTHORITY = {
    "model_p": False,
    "promotion": False,
    "staking": False,
    "official": False,
    "run_it": False,
}

# Conservative FBS full-game plausibility. Outside this band the snapshot is
# treated as an unstable/malformed provider line, not a tradable quote.
SPREAD_ABS_MAX = 75.0
TOTAL_MIN = 20.0
TOTAL_MAX = 110.0


class CFBLineIntegrityError(ValueError):
    pass


def _num(value: object, field: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise CFBLineIntegrityError(f"CFB_LINE_NOT_NUMERIC:{field}") from exc
    if out != out:
        raise CFBLineIntegrityError(f"CFB_LINE_NAN:{field}")
    return out


def canonicalize_spread_pair(home_point: object, away_point: object) -> float:
    home = _num(home_point, "spread.home")
    away = _num(away_point, "spread.away")
    if abs(home) > SPREAD_ABS_MAX or abs(away) > SPREAD_ABS_MAX:
        raise CFBLineIntegrityError("CFB_SPREAD_IMPLAUSIBLE")
    if abs(home + away) > 1e-9:
        raise CFBLineIntegrityError("CFB_SPREAD_PAIR_NOT_OPPOSITE")
    return home


def canonicalize_total_pair(over_point: object, under_point: object) -> float:
    over = _num(over_point, "total.over")
    under = _num(under_point, "total.under")
    if over != under:
        raise CFBLineIntegrityError("CFB_TOTAL_PAIR_MISMATCH")
    if over < TOTAL_MIN or over > TOTAL_MAX:
        raise CFBLineIntegrityError("CFB_TOTAL_IMPLAUSIBLE")
    return over


def validate_period_is_full_game(period: object) -> None:
    if str(period or "").strip().upper() != "FG":
        raise CFBLineIntegrityError("CFB_PERIOD_NOT_FULL_GAME")


def audit_quote_snapshot(quotes: Iterable[Mapping[str, object]]) -> dict[str, int]:
    """Group captured FG quotes and reject conflicting pairs.

    Moneyline sides are counted only; they are not pair-canonicalized here.
    """
    grouped: dict[tuple[str, str, str, str], list[Mapping[str, object]]] = defaultdict(list)
    counts = {"quotes": 0, "spread_pairs": 0, "total_pairs": 0, "moneylines": 0}
    for raw in quotes:
        counts["quotes"] += 1
        period = raw.get("period", "FG")
        validate_period_is_full_game(period)
        game_id = str(raw.get("game_id") or "").strip()
        book = str(raw.get("book_key") or raw.get("sportsbook") or "").strip().lower()
        market = str(raw.get("market") or "").strip().upper()
        retrieved = str(raw.get("retrieved_at") or "").strip()
        if not game_id or not book or market not in {"MONEYLINE", "SPREAD", "TOTAL"}:
            raise CFBLineIntegrityError("CFB_QUOTE_IDENTITY_INVALID")
        grouped[(game_id, book, market, retrieved)].append(dict(raw))

    for (_game, _book, market, _ts), rows in grouped.items():
        sides = [str(r.get("side") or "").strip().upper() for r in rows]
        if market == "MONEYLINE":
            if sorted(set(sides)) != ["AWAY", "HOME"] or len(rows) != 2:
                raise CFBLineIntegrityError("CFB_MONEYLINE_PAIR_INCOMPLETE")
            counts["moneylines"] += 1
            continue
        if market == "SPREAD":
            by_side = {str(r.get("side") or "").upper(): r for r in rows}
            if set(by_side) != {"HOME", "AWAY"} or len(rows) != 2:
                raise CFBLineIntegrityError("CFB_SPREAD_PAIR_INCOMPLETE")
            home_line = _num(by_side["HOME"].get("line"), "spread.home")
            away_line = _num(by_side["AWAY"].get("line"), "spread.away")
            # Accept either raw opposite points or already-canonical home line on both sides.
            if abs(home_line - away_line) <= 1e-9:
                if abs(home_line) > SPREAD_ABS_MAX:
                    raise CFBLineIntegrityError("CFB_SPREAD_IMPLAUSIBLE")
            else:
                canonicalize_spread_pair(home_line, away_line)
            counts["spread_pairs"] += 1
            continue
        by_side = {str(r.get("side") or "").upper(): r for r in rows}
        if set(by_side) != {"OVER", "UNDER"} or len(rows) != 2:
            raise CFBLineIntegrityError("CFB_TOTAL_PAIR_INCOMPLETE")
        canonicalize_total_pair(by_side["OVER"].get("line"), by_side["UNDER"].get("line"))
        counts["total_pairs"] += 1
    return counts
