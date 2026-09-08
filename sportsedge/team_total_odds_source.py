"""Fail-closed event-level acquisition for MLB full-game team totals.

The Odds API exposes ``team_totals`` through the per-event odds endpoint. Team
identity is resolved exactly against the MLB StatsAPI game; no fuzzy team matching
or player-style participant mapping is used.

After provider-event binding, quotes carry both the provider event id and the
independently acquired official MLB event/team/game-number identity required by
the downstream binding boundary. These fields are emitted here, not synthesized
by model or orchestration code.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Iterable, Mapping
from urllib.request import urlopen

from .mlb_source import GameSnapshot
from .odds_api_source import (
    DEFAULT_BOOKMAKERS,
    DEFAULT_TTL_SECONDS,
    OddsApiSourceError,
    _event_url,
    _get_json,
    bind_provider_event,
    normalize_name,
)
from .runtime import parse_timestamp

TEAM_TOTAL_PROVIDER_MARKET = "team_totals"


class TeamTotalOddsSourceError(RuntimeError):
    pass


@dataclass(frozen=True)
class TeamTotalOddsSnapshot:
    quotes: tuple[dict[str, Any], ...]
    failures: tuple[dict[str, Any], ...]


def _updated(market: Mapping[str, Any], bookmaker: Mapping[str, Any]) -> datetime:
    raw = market.get("last_update") or bookmaker.get("last_update")
    try:
        return parse_timestamp(raw)
    except Exception as exc:
        raise TeamTotalOddsSourceError("ODDS_MARKET_TIMESTAMP_INVALID") from exc


def _team(name: Any, game: GameSnapshot) -> tuple[str, int, str]:
    key = normalize_name(name)
    if key == normalize_name(game.home_name):
        return "HOME", int(game.home_id), str(game.home_name)
    if key == normalize_name(game.away_name):
        return "AWAY", int(game.away_id), str(game.away_name)
    raise TeamTotalOddsSourceError("ODDS_GAME_TEAM_UNRESOLVED")


def _official_binding_identity(game: GameSnapshot) -> dict[str, Any]:
    out: dict[str, Any] = {
        "event_id": str(game.game_pk),
        "event_home_team_id": str(game.home_id),
        "event_away_team_id": str(game.away_id),
    }
    if game.game_number is not None:
        out["game_number"] = int(game.game_number)
    return out


def parse_team_total_event_odds(
    payload: Mapping[str, Any],
    *,
    game: GameSnapshot,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    provider_event: Mapping[str, Any] | None = None,
) -> TeamTotalOddsSnapshot:
    quotes: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    if not isinstance(payload, Mapping):
        return TeamTotalOddsSnapshot((), ({"reason": "ODDS_EVENT_ODDS_MALFORMED", "game_id": str(game.game_pk)},))

    provider_event_id = ""
    if isinstance(provider_event, Mapping):
        provider_event_id = str(provider_event.get("id") or "").strip()
    if not provider_event_id:
        provider_event_id = str(payload.get("id") or "").strip()
    official_identity = _official_binding_identity(game)

    for bookmaker in payload.get("bookmakers") or []:
        if not isinstance(bookmaker, Mapping):
            failures.append({"reason": "ODDS_BOOKMAKER_MALFORMED", "game_id": str(game.game_pk)})
            continue
        book_key = str(bookmaker.get("key") or "").strip()
        book_title = str(bookmaker.get("title") or book_key).strip()
        for market in bookmaker.get("markets") or []:
            if not isinstance(market, Mapping):
                failures.append({"reason": "ODDS_MARKET_MALFORMED", "game_id": str(game.game_pk), "book_key": book_key})
                continue
            market_key = str(market.get("key") or "").strip()
            if market_key != TEAM_TOTAL_PROVIDER_MARKET:
                continue
            try:
                retrieved_at = _updated(market, bookmaker)
            except Exception as exc:
                failures.append({"reason": str(exc), "game_id": str(game.game_pk), "book_key": book_key, "raw_market_name": market_key})
                continue

            for outcome in market.get("outcomes") or []:
                try:
                    if not isinstance(outcome, Mapping):
                        raise TeamTotalOddsSourceError("ODDS_OUTCOME_MALFORMED")
                    price = outcome.get("price")
                    if price is None:
                        raise TeamTotalOddsSourceError("ODDS_OUTCOME_PRICE_MISSING")
                    point = outcome.get("point")
                    if point is None:
                        raise TeamTotalOddsSourceError("ODDS_OUTCOME_LINE_MISSING")
                    side = str(outcome.get("name") or "").strip().upper()
                    if side not in {"OVER", "UNDER"}:
                        raise TeamTotalOddsSourceError("ODDS_SIDE_UNSUPPORTED")
                    team_side, team_id, team_name = _team(outcome.get("description"), game)
                    quote: dict[str, Any] = {
                        "game_id": str(game.game_pk),
                        "period": "FG",
                        "market": "TEAM_TOTALS",
                        "entity_id": str(team_id),
                        "side": side,
                        "selection": f"{team_name} {side.title()}",
                        "line": point,
                        "american_odds": price,
                        "book_key": book_key,
                        "sportsbook": book_title,
                        "retrieved_at": retrieved_at,
                        "ttl_seconds": ttl_seconds,
                        "raw_market_name": market_key,
                        "is_alternate": False,
                        "team_side": team_side,
                        "provider_team_name": team_name,
                        "away_team": str(game.away_name),
                        "home_team": str(game.home_name),
                        **official_identity,
                    }
                    if provider_event_id:
                        quote["provider_event_id"] = provider_event_id
                    if outcome.get("sid") not in (None, ""):
                        quote["offer_id"] = str(outcome["sid"])
                    quotes.append(quote)
                except Exception as exc:
                    failures.append({
                        "reason": f"{type(exc).__name__}:{exc}",
                        "game_id": str(game.game_pk),
                        "book_key": book_key,
                        "raw_market_name": market_key,
                        "selection": str(outcome.get("name") if isinstance(outcome, Mapping) else ""),
                        "team": str(outcome.get("description") if isinstance(outcome, Mapping) else ""),
                    })
    return TeamTotalOddsSnapshot(tuple(quotes), tuple(failures))


def fetch_mlb_team_total_quotes(
    *,
    api_key: str,
    schedule: Iterable[GameSnapshot],
    opener: Callable = urlopen,
    bookmakers: Iterable[str] = DEFAULT_BOOKMAKERS,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> TeamTotalOddsSnapshot:
    games = list(schedule)
    events = _get_json(_event_url("/sports/baseball_mlb/events", api_key=api_key), opener=opener, label="events:team-totals")
    if not isinstance(events, list):
        raise OddsApiSourceError("ODDS_EVENTS_RESPONSE_NOT_LIST")
    requested_books = ",".join(str(x).strip() for x in bookmakers if str(x).strip())
    if not requested_books:
        raise OddsApiSourceError("ODDS_BOOKMAKERS_MISSING")

    quotes: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for event in events:
        try:
            game = bind_provider_event(event, games)
            event_id = str(event.get("id") or "").strip()
            if not event_id:
                raise TeamTotalOddsSourceError("ODDS_EVENT_ID_MISSING")
            url = _event_url(
                f"/sports/baseball_mlb/events/{event_id}/odds",
                api_key=api_key,
                params={
                    "bookmakers": requested_books,
                    "markets": TEAM_TOTAL_PROVIDER_MARKET,
                    "oddsFormat": "american",
                    "dateFormat": "iso",
                    "includeSids": "true",
                },
            )
            snap = parse_team_total_event_odds(
                _get_json(url, opener=opener, label=f"team-totals:{event_id}"),
                game=game,
                ttl_seconds=ttl_seconds,
                provider_event=event,
            )
            quotes.extend(snap.quotes)
            failures.extend(snap.failures)
        except Exception as exc:
            failures.append({
                "reason": f"{type(exc).__name__}:{exc}",
                "provider_event_id": str(event.get("id") if isinstance(event, Mapping) else ""),
            })
    return TeamTotalOddsSnapshot(tuple(quotes), tuple(failures))
