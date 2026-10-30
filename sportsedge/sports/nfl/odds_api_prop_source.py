"""The Odds API NFL player-prop acquisition for forward evidence capture.

This is a market-data source only. It never creates Model_P, promotion status,
or eligibility. Event-level requests are required by the provider for props.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlencode

from sportsedge.odds_keyring import fetch_with_key_failover
from .odds_source import _BASE, _SPORT, _http_fetch

MARKET_KEYS = {
    "ANYTIME_TD": "player_anytime_td",
    "RECEPTIONS": "player_receptions",
    "RECEIVING_YARDS": "player_reception_yds",
    "RUSHING_YARDS": "player_rush_yds",
    "RUSH_ATTEMPTS": "player_rush_attempts",
    "PASSING_YARDS": "player_pass_yds",
    "PASS_ATTEMPTS": "player_pass_attempts",
    "COMPLETIONS": "player_pass_completions",
    "PASSING_TDS": "player_pass_tds",
    "INTERCEPTIONS": "player_pass_interceptions",
}


class NFLPropOddsSourceError(ValueError):
    pass


def build_nfl_prop_odds_url(*, event_id: str, bookmakers: str = "draftkings,fanduel") -> str:
    clean = str(event_id or "").strip()
    if not clean or "/" in clean:
        raise NFLPropOddsSourceError("NFL_PROP_ODDS_EVENT_ID_INVALID")
    params = {
        "regions": "us",
        "bookmakers": bookmakers,
        "markets": ",".join(MARKET_KEYS.values()),
        "oddsFormat": "american",
        "dateFormat": "iso",
    }
    return f"{_BASE}/sports/{_SPORT}/events/{clean}/odds?{urlencode(params)}"


def fetch_nfl_prop_odds(
    api_keys: Sequence[str],
    *,
    event_id: str,
    bookmakers: str = "draftkings,fanduel",
    fetcher: Callable[[str, str], Any] = _http_fetch,
):
    base = build_nfl_prop_odds_url(event_id=event_id, bookmakers=bookmakers)
    result = fetch_with_key_failover(list(api_keys), lambda key: fetcher(base, key))
    if not isinstance(result.value, Mapping):
        raise NFLPropOddsSourceError("NFL_PROP_ODDS_RESPONSE_NOT_OBJECT")
    return result


def normalize_nfl_prop_event(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    event_id = str(payload.get("id") or "").strip()
    commence = str(payload.get("commence_time") or "").strip()
    if not event_id:
        raise NFLPropOddsSourceError("NFL_PROP_ODDS_EVENT_ID_MISSING")
    if not commence:
        raise NFLPropOddsSourceError("NFL_PROP_ODDS_COMMENCE_TIME_MISSING")
    reverse = {provider: canonical for canonical, provider in MARKET_KEYS.items()}
    rows: list[dict[str, Any]] = []
    for bookmaker in payload.get("bookmakers") or []:
        if not isinstance(bookmaker, Mapping):
            continue
        book_key = str(bookmaker.get("key") or "").strip().lower()
        if not book_key:
            continue
        for market in bookmaker.get("markets") or []:
            if not isinstance(market, Mapping):
                continue
            canonical = reverse.get(str(market.get("key") or "").strip())
            if canonical is None:
                continue
            observed_at = str(market.get("last_update") or bookmaker.get("last_update") or "").strip()
            if not observed_at:
                raise NFLPropOddsSourceError("NFL_PROP_ODDS_OBSERVED_AT_MISSING")
            for outcome in market.get("outcomes") or []:
                if not isinstance(outcome, Mapping):
                    continue
                player = str(outcome.get("description") or outcome.get("name") or "").strip()
                side = str(outcome.get("name") or "").strip().upper()
                if not player:
                    raise NFLPropOddsSourceError("NFL_PROP_ODDS_PLAYER_MISSING")
                if canonical == "ANYTIME_TD":
                    if side not in {"YES", "NO"}:
                        side = "YES" if side == player.upper() else side
                    if side not in {"YES", "NO"}:
                        raise NFLPropOddsSourceError("NFL_PROP_ODDS_ANYTIME_TD_SIDE_INVALID")
                    line = None
                else:
                    if side not in {"OVER", "UNDER"}:
                        raise NFLPropOddsSourceError("NFL_PROP_ODDS_SIDE_INVALID")
                    if outcome.get("point") is None:
                        raise NFLPropOddsSourceError("NFL_PROP_ODDS_LINE_MISSING")
                    line = float(outcome["point"])
                try:
                    price = int(outcome["price"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise NFLPropOddsSourceError("NFL_PROP_ODDS_PRICE_INVALID") from exc
                rows.append({
                    "provider_event_id": event_id,
                    "game_start": commence,
                    "market": canonical,
                    "entity_name": player,
                    "entity_name_normalized": " ".join(player.lower().split()),
                    "side": side,
                    "line": line,
                    "american_odds": price,
                    "sportsbook": book_key,
                    "book_key": book_key,
                    "retrieved_at": observed_at,
                    "provider": "THE_ODDS_API",
                    "promotion_authority": False,
                    "model_p_created": False,
                })
    return rows
