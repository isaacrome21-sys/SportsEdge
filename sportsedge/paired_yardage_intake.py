"""Strict DK NFL yardage main-line pair intake, independent of obsolete runners.

No generated opponent side, guessed price, fixture or timestamps. A caller must
supply a real paired board quote with provenance; this component is not a
validated probability model or a publication permission.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Mapping

YARDAGE_FAMILIES = frozenset({"RECEIVING_YARDS", "RUSHING_YARDS", "PASSING_YARDS"})


class YardagePairRefusal(ValueError):
    pass


def _required_string(quote: Mapping, key: str) -> str:
    value = quote.get(key)
    if not isinstance(value, str) or not value.strip():
        raise YardagePairRefusal("MISSING_" + key.upper())
    return value.strip()


def _odds(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value == 0 or -100 < value < 100:
        raise YardagePairRefusal("INVALID_AMERICAN_ODDS")
    return value


def _clock(value: object) -> datetime:
    # RUN IT --lines is JSON; captured_at arrives as an offset-aware ISO
    # string in live operation. Accept datetime for in-process callers, but
    # never infer a timezone or accept a naive captured instant.
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (TypeError, ValueError, OverflowError):
            raise YardagePairRefusal("PIT_CAPTURE_TIME_REQUIRED") from None
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise YardagePairRefusal("PIT_CAPTURE_TIME_REQUIRED")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise YardagePairRefusal("PIT_CAPTURE_TIME_REQUIRED")
    return parsed.astimezone(timezone.utc)


def bind_nfl_yardage_pair(quote: Mapping, *, as_of: datetime, max_age_seconds: int = 180) -> tuple[dict, dict]:
    """Return OVER and UNDER only for one exact real DK captured main-line pair."""
    if not isinstance(quote, Mapping):
        raise YardagePairRefusal("QUOTE_MAPPING_REQUIRED")
    if max_age_seconds <= 0:
        raise YardagePairRefusal("INVALID_FRESHNESS_BOUND")
    sport = _required_string(quote, "sport").upper()
    market = _required_string(quote, "market").upper()
    if sport != "NFL" or market not in YARDAGE_FAMILIES:
        raise YardagePairRefusal("NOT_NFL_YARDAGE_MAIN")
    book = _required_string(quote, "book").upper()
    if book not in {"DRAFTKINGS", "DK"}:
        raise YardagePairRefusal("NOT_DK_QUOTE")
    identity = {key: _required_string(quote, key) for key in ("game_id", "player_id", "team", "capture_id", "player_name", "away", "home", "kickoff")}
    line = quote.get("line")
    if isinstance(line, bool) or not isinstance(line, (int, float)) or not isfinite(line) or line < 0:
        raise YardagePairRefusal("INVALID_YARDAGE_LINE")
    if quote.get("over_line", line) != line or quote.get("under_line", line) != line:
        raise YardagePairRefusal("PAIR_LINE_MISMATCH")
    if quote.get("over_game_id", identity["game_id"]) != identity["game_id"] or quote.get("under_game_id", identity["game_id"]) != identity["game_id"]:
        raise YardagePairRefusal("PAIR_FIXTURE_MISMATCH")
    if quote.get("over_player_id", identity["player_id"]) != identity["player_id"] or quote.get("under_player_id", identity["player_id"]) != identity["player_id"]:
        raise YardagePairRefusal("PAIR_PLAYER_MISMATCH")
    # Both prices must be observed. Never manufacture a reciprocal side.
    over, under = _odds(quote.get("over_odds")), _odds(quote.get("under_odds"))
    captured, cutoff = _clock(quote.get("captured_at")), _clock(as_of)
    age = (cutoff - captured).total_seconds()
    if age < 0:
        raise YardagePairRefusal("FUTURE_QUOTE")
    if age > max_age_seconds:
        raise YardagePairRefusal("STALE_QUOTE")
    common = dict(identity, sport="NFL", market="PLAYER_" + market, book="DRAFTKINGS", line=float(line),
                  quote_captured_at=(quote["captured_at"] if isinstance(quote["captured_at"], str)
                                     else captured.isoformat()),
                  captured_at=(quote["captured_at"] if isinstance(quote["captured_at"], str)
                               else captured.isoformat()))
    return ({**common, "side": "OVER", "odds": over}, {**common, "side": "UNDER", "odds": under})
