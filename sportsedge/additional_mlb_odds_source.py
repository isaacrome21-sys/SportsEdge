"""Fail-closed acquisition for the seven non-count MLB markets missing from
featured-game and direct-DraftKings count-prop sources.

Provider capability is intentionally explicit and derived only from documented
The Odds API market keys:
- F5 moneyline/spread/total
- 1st-inning total (used for NRFI/YRFI only when the posted line is exactly 0.5)
- batter first home run
- pitcher to record a win

Provider event/player identity is resolved with the same exact binders used by
existing SportsEdge Odds API acquisition. No fuzzy matching is introduced.
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
    _participant_id,
    bind_provider_event,
    normalize_name,
)
from .runtime import parse_timestamp

PROVIDER_MARKETS = (
    "h2h_1st_5_innings",
    "spreads_1st_5_innings",
    "totals_1st_5_innings",
    "totals_1st_1_innings",
    "batter_first_home_run",
    "pitcher_record_a_win",
)

CANONICAL_MARKETS = frozenset(
    {
        "F5_MONEYLINE",
        "F5_RUN_LINE",
        "F5_TOTALS",
        "NRFI",
        "YRFI",
        "FIRST_HOME_RUN",
        "PITCHER_RECORD_WIN",
    }
)


class AdditionalMLBOddsSourceError(RuntimeError):
    pass


@dataclass(frozen=True)
class AdditionalMLBOddsSnapshot:
    quotes: tuple[dict[str, Any], ...]
    failures: tuple[dict[str, Any], ...]


def _updated(market: Mapping[str, Any], bookmaker: Mapping[str, Any]) -> datetime:
    raw = market.get("last_update") or bookmaker.get("last_update")
    try:
        return parse_timestamp(raw)
    except Exception as exc:
        raise AdditionalMLBOddsSourceError("ODDS_MARKET_TIMESTAMP_INVALID") from exc


def _team_side(name: Any, game: GameSnapshot) -> tuple[str, int]:
    key = normalize_name(name)
    if key == normalize_name(game.home_name):
        return "HOME", int(game.home_id)
    if key == normalize_name(game.away_name):
        return "AWAY", int(game.away_id)
    raise AdditionalMLBOddsSourceError("ODDS_GAME_TEAM_UNRESOLVED")


def _base_quote(
    *,
    game: GameSnapshot,
    book_key: str,
    book_title: str,
    retrieved_at: datetime,
    ttl_seconds: int,
    raw_market_name: str,
    provider_event: Mapping[str, Any] | None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "game_id": str(game.game_pk),
        "book_key": book_key,
        "sportsbook": book_title,
        "retrieved_at": retrieved_at,
        "ttl_seconds": ttl_seconds,
        "raw_market_name": raw_market_name,
        "is_alternate": False,
        "away_team": str(game.away_name),
        "home_team": str(game.home_name),
    }
    if isinstance(provider_event, Mapping):
        event_id = str(provider_event.get("id") or "").strip()
        if event_id:
            out["provider_event_id"] = event_id
    return out


def _binary_side(value: Any) -> str:
    side = str(value or "").strip().upper()
    if side not in {"YES", "NO"}:
        raise AdditionalMLBOddsSourceError("ODDS_BINARY_SIDE_UNSUPPORTED")
    return side


def parse_additional_event_odds(
    payload: Mapping[str, Any],
    *,
    game: GameSnapshot,
    participant_index: Mapping[int, Mapping[str, int]],
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    provider_event: Mapping[str, Any] | None = None,
) -> AdditionalMLBOddsSnapshot:
    quotes: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    if not isinstance(payload, Mapping):
        return AdditionalMLBOddsSnapshot(
            (),
            ({"reason": "ODDS_EVENT_ODDS_MALFORMED", "game_id": str(game.game_pk)},),
        )

    for bookmaker in payload.get("bookmakers") or []:
        if not isinstance(bookmaker, Mapping):
            failures.append({"reason": "ODDS_BOOKMAKER_MALFORMED", "game_id": str(game.game_pk)})
            continue
        book_key = str(bookmaker.get("key") or "").strip()
        book_title = str(bookmaker.get("title") or book_key).strip()
        for market in bookmaker.get("markets") or []:
            if not isinstance(market, Mapping):
                failures.append(
                    {
                        "reason": "ODDS_MARKET_MALFORMED",
                        "game_id": str(game.game_pk),
                        "book_key": book_key,
                    }
                )
                continue
            market_key = str(market.get("key") or "").strip()
            if market_key not in PROVIDER_MARKETS:
                continue
            try:
                retrieved_at = _updated(market, bookmaker)
            except Exception as exc:
                failures.append(
                    {
                        "reason": str(exc),
                        "game_id": str(game.game_pk),
                        "book_key": book_key,
                        "raw_market_name": market_key,
                    }
                )
                continue

            base = _base_quote(
                game=game,
                book_key=book_key,
                book_title=book_title,
                retrieved_at=retrieved_at,
                ttl_seconds=ttl_seconds,
                raw_market_name=market_key,
                provider_event=provider_event,
            )

            for outcome in market.get("outcomes") or []:
                try:
                    if not isinstance(outcome, Mapping):
                        raise AdditionalMLBOddsSourceError("ODDS_OUTCOME_MALFORMED")
                    price = outcome.get("price")
                    if price is None:
                        raise AdditionalMLBOddsSourceError("ODDS_OUTCOME_PRICE_MISSING")

                    if market_key == "h2h_1st_5_innings":
                        side, team_id = _team_side(outcome.get("name"), game)
                        quote = {
                            **base,
                            "period": "F5",
                            "market": "F5_MONEYLINE",
                            "entity_id": str(team_id),
                            "side": side,
                            "selection": str(outcome.get("name") or "").strip(),
                            "line": 0.0,
                            "american_odds": price,
                        }
                        quotes.append(quote)

                    elif market_key == "spreads_1st_5_innings":
                        side, team_id = _team_side(outcome.get("name"), game)
                        point = outcome.get("point")
                        if point is None:
                            raise AdditionalMLBOddsSourceError("ODDS_OUTCOME_LINE_MISSING")
                        quotes.append(
                            {
                                **base,
                                "period": "F5",
                                "market": "F5_RUN_LINE",
                                "entity_id": str(team_id),
                                "side": side,
                                "selection": str(outcome.get("name") or "").strip(),
                                "line": point,
                                "american_odds": price,
                            }
                        )

                    elif market_key == "totals_1st_5_innings":
                        side = str(outcome.get("name") or "").strip().upper()
                        if side not in {"OVER", "UNDER"}:
                            raise AdditionalMLBOddsSourceError("ODDS_SIDE_UNSUPPORTED")
                        point = outcome.get("point")
                        if point is None:
                            raise AdditionalMLBOddsSourceError("ODDS_OUTCOME_LINE_MISSING")
                        quotes.append(
                            {
                                **base,
                                "period": "F5",
                                "market": "F5_TOTALS",
                                "entity_id": str(game.game_pk),
                                "side": side,
                                "selection": side.title(),
                                "line": point,
                                "american_odds": price,
                            }
                        )

                    elif market_key == "totals_1st_1_innings":
                        point = outcome.get("point")
                        try:
                            line = float(point)
                        except (TypeError, ValueError) as exc:
                            raise AdditionalMLBOddsSourceError("ODDS_OUTCOME_LINE_MISSING") from exc
                        if abs(line - 0.5) > 1e-12:
                            raise AdditionalMLBOddsSourceError("NRFI_YRFI_REQUIRES_FIRST_INNING_0_5_TOTAL")
                        raw_side = str(outcome.get("name") or "").strip().upper()
                        if raw_side not in {"OVER", "UNDER"}:
                            raise AdditionalMLBOddsSourceError("ODDS_SIDE_UNSUPPORTED")
                        if raw_side == "OVER":
                            mappings = (("YRFI", "YES"), ("NRFI", "NO"))
                        else:
                            mappings = (("NRFI", "YES"), ("YRFI", "NO"))
                        for canonical_market, canonical_side in mappings:
                            quotes.append(
                                {
                                    **base,
                                    "period": "1ST",
                                    "market": canonical_market,
                                    "entity_id": str(game.game_pk),
                                    "side": canonical_side,
                                    "selection": canonical_side.title(),
                                    "line": 0.0,
                                    "provider_line": 0.5,
                                    "provider_side": raw_side,
                                    "american_odds": price,
                                }
                            )

                    elif market_key in {"batter_first_home_run", "pitcher_record_a_win"}:
                        side = _binary_side(outcome.get("name"))
                        provider_participant_name = str(outcome.get("description") or "").strip()
                        if not provider_participant_name:
                            raise AdditionalMLBOddsSourceError("ODDS_PLAYER_NAME_MISSING")
                        player_id = _participant_id(
                            provider_participant_name,
                            game_pk=game.game_pk,
                            participant_index=participant_index,
                        )
                        canonical_market = (
                            "FIRST_HOME_RUN"
                            if market_key == "batter_first_home_run"
                            else "PITCHER_RECORD_WIN"
                        )
                        quote = {
                            **base,
                            "period": "FG",
                            "market": canonical_market,
                            "entity_id": str(player_id),
                            "provider_participant_name": provider_participant_name,
                            "provider_participant_name_normalized": normalize_name(provider_participant_name),
                            "side": side,
                            "selection": side.title(),
                            "line": 0.0,
                            "american_odds": price,
                        }
                        if outcome.get("sid") not in (None, ""):
                            quote["offer_id"] = str(outcome["sid"])
                        quotes.append(quote)

                except Exception as exc:
                    failures.append(
                        {
                            "reason": f"{type(exc).__name__}:{exc}",
                            "game_id": str(game.game_pk),
                            "book_key": book_key,
                            "raw_market_name": market_key,
                            "selection": str(outcome.get("name") if isinstance(outcome, Mapping) else ""),
                            "participant": str(outcome.get("description") if isinstance(outcome, Mapping) else ""),
                        }
                    )

    return AdditionalMLBOddsSnapshot(tuple(quotes), tuple(failures))


def fetch_mlb_additional_quotes(
    *,
    api_key: str,
    schedule: Iterable[GameSnapshot],
    participant_index: Mapping[int, Mapping[str, int]],
    opener: Callable = urlopen,
    bookmakers: Iterable[str] = DEFAULT_BOOKMAKERS,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> AdditionalMLBOddsSnapshot:
    games = list(schedule)
    events_url = _event_url(f"/sports/baseball_mlb/events", api_key=api_key)
    events = _get_json(events_url, opener=opener, label="events:additional")
    if not isinstance(events, list):
        raise OddsApiSourceError("ODDS_EVENTS_RESPONSE_NOT_LIST")

    requested_books = ",".join(str(x).strip() for x in bookmakers if str(x).strip())
    if not requested_books:
        raise OddsApiSourceError("ODDS_BOOKMAKERS_MISSING")
    requested_markets = ",".join(PROVIDER_MARKETS)

    quotes: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for event in events:
        try:
            game = bind_provider_event(event, games)
            event_id = str(event.get("id") or "").strip()
            if not event_id:
                raise AdditionalMLBOddsSourceError("ODDS_EVENT_ID_MISSING")
            url = _event_url(
                f"/sports/baseball_mlb/events/{event_id}/odds",
                api_key=api_key,
                params={
                    "bookmakers": requested_books,
                    "markets": requested_markets,
                    "oddsFormat": "american",
                    "dateFormat": "iso",
                    "includeSids": "true",
                },
            )
            snap = parse_additional_event_odds(
                _get_json(url, opener=opener, label=f"additional-event:{event_id}"),
                game=game,
                participant_index=participant_index,
                ttl_seconds=ttl_seconds,
                provider_event=event,
            )
            quotes.extend(snap.quotes)
            failures.extend(snap.failures)
        except Exception as exc:
            failures.append(
                {
                    "reason": f"{type(exc).__name__}:{exc}",
                    "provider_event_id": str(event.get("id") if isinstance(event, Mapping) else ""),
                }
            )
    return AdditionalMLBOddsSnapshot(tuple(quotes), tuple(failures))
