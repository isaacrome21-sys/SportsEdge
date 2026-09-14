"""Research-only direct DraftKings MLB player-prop acquisition.

Unknown labels are skipped rather than guessed. Expanded joint-market labels are
normalized only when the provider names the proposition explicitly.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .odds_api_source import normalize_name

DK_HOME = "https://sportsbook.draftkings.com/"
DEFAULT_TTL_SECONDS = 120

MARKET_LABELS = {
    "home runs": "HOME_RUNS", "home run": "HOME_RUNS",
    "hits": "HITS", "total bases": "TOTAL_BASES", "rbis": "RBI", "rbi": "RBI",
    "runs": "RUNS", "runs scored": "RUNS", "stolen bases": "STOLEN_BASES",
    "walks": "BATTER_BB", "strikeouts": "BATTER_K",
    "singles": "SINGLES", "doubles": "DOUBLES", "triples": "TRIPLES",
    "extra base hits": "EXTRA_BASE_HITS", "extra-base hits": "EXTRA_BASE_HITS",
    "hits + runs + rbis": "HITS_RUNS_RBIS", "hits+runs+rbis": "HITS_RUNS_RBIS",
    "hits + runs + stolen bases": "HITS_RUNS_STOLEN_BASES",
    "hits+runs+stolen bases": "HITS_RUNS_STOLEN_BASES",
    "runs + rbis": "RUNS_RBIS", "runs+rbis": "RUNS_RBIS",
    "hits + stolen bases": "HITS_STOLEN_BASES", "hits+stolen bases": "HITS_STOLEN_BASES",
    "hits + walks + stolen bases": "HITS_WALKS_STOLEN_BASES",
    "hits+walks+stolen bases": "HITS_WALKS_STOLEN_BASES",
    "hits + walks + sb": "HITS_WALKS_STOLEN_BASES", "hits+walks+sb": "HITS_WALKS_STOLEN_BASES",
    "pitcher strikeouts": "PITCHER_K", "strikeouts thrown": "PITCHER_K",
    "hits allowed": "PITCHER_HITS_ALLOWED", "pitcher hits allowed": "PITCHER_HITS_ALLOWED",
    "pitcher walks": "PITCHER_BB", "walks allowed": "PITCHER_BB",
    "earned runs allowed": "PITCHER_ER", "earned runs": "PITCHER_ER",
    "outs recorded": "PITCHER_OUTS", "pitcher outs recorded": "PITCHER_OUTS",
    "hits allowed + walks allowed + earned runs allowed": "PITCHER_HITS_WALKS_ER",
    "hits + walks + earned runs allowed": "PITCHER_HITS_WALKS_ER",
    "pitcher hits + walks + earned runs": "PITCHER_HITS_WALKS_ER",
    "either pitcher hits allowed": "EITHER_PITCHER_HITS_ALLOWED",
    "either pitcher walks allowed": "EITHER_PITCHER_BB",
    "either pitcher earned runs allowed": "EITHER_PITCHER_ER",
}

COUNT_MARKETS = frozenset({
    "HITS", "HOME_RUNS", "TOTAL_BASES", "RBI", "RUNS", "STOLEN_BASES", "BATTER_BB", "BATTER_K",
    "SINGLES", "DOUBLES", "TRIPLES", "EXTRA_BASE_HITS", "HITS_RUNS_RBIS", "HITS_RUNS_STOLEN_BASES",
    "RUNS_RBIS", "HITS_STOLEN_BASES", "HITS_WALKS_STOLEN_BASES", "PITCHER_K", "PITCHER_HITS_ALLOWED",
    "PITCHER_BB", "PITCHER_ER", "PITCHER_OUTS", "PITCHER_HITS_WALKS_ER",
    "EITHER_PITCHER_HITS_ALLOWED", "EITHER_PITCHER_BB", "EITHER_PITCHER_ER",
})


class DraftKingsPropSourceError(RuntimeError):
    pass


@dataclass(frozen=True)
class DraftKingsPropSnapshot:
    quotes: tuple[dict[str, Any], ...]
    failures: tuple[dict[str, Any], ...]
    league_id: int | None = None
    base_url: str | None = None


def _request(url: str, *, opener: Callable = urlopen, timeout: int = 15) -> bytes:
    req = Request(
        url,
        headers={
            "Accept": "application/json,text/html,*/*",
            "User-Agent": "Mozilla/5.0 SportsEdge-DK-Research/1",
            "Referer": DK_HOME,
            "Origin": "https://sportsbook.draftkings.com",
        },
    )
    with opener(req, timeout=timeout) as response:
        return response.read()


def _json(url: str, *, opener: Callable = urlopen) -> Any:
    raw = _request(url, opener=opener)
    try:
        return json.loads(raw)
    except Exception as exc:
        raise DraftKingsPropSourceError("DK_RESPONSE_NOT_JSON") from exc


def _discover(home_html: str) -> tuple[str, int]:
    config_match = re.search(r"window\.__productConfig\s*=\s*({.*?})\s*;", home_html, re.S)
    state_match = re.search(r"window\.__INITIAL_STATE__\s*=\s*({.*?})\s*;", home_html, re.S)
    if not config_match or not state_match:
        raise DraftKingsPropSourceError("DK_BOOTSTRAP_STATE_MISSING")
    try:
        config = json.loads(config_match.group(1))
        state = json.loads(state_match.group(1))
    except Exception as exc:
        raise DraftKingsPropSourceError("DK_BOOTSTRAP_JSON_INVALID") from exc
    base = str(config.get("sportsContentBff") or "").strip()
    if not base.startswith("https://"):
        raise DraftKingsPropSourceError("DK_SPORTS_CONTENT_BASE_MISSING")
    if not base.endswith("/"):
        base += "/"
    mlb_id = None
    for sport in ((state.get("sports") or {}).get("data") or []):
        for league in sport.get("eventGroupInfos") or []:
            name = str(league.get("eventGroupName") or "").lower()
            if "mlb" in name or "major league baseball" in name:
                try:
                    mlb_id = int(league["eventGroupId"])
                except Exception:
                    continue
                break
        if mlb_id is not None:
            break
    if mlb_id is None:
        raise DraftKingsPropSourceError("DK_MLB_LEAGUE_ID_NOT_FOUND")
    return base, mlb_id


def _american_from_decimal(value: Any) -> int:
    try:
        dec = float(value)
    except Exception as exc:
        raise DraftKingsPropSourceError("DK_ODDS_INVALID") from exc
    if dec <= 1.0:
        raise DraftKingsPropSourceError("DK_ODDS_INVALID")
    return int(round((dec - 1.0) * 100.0)) if dec >= 2.0 else int(round(-100.0 / (dec - 1.0)))


def _selection_price(row: Mapping[str, Any]) -> int:
    for key in ("displayOdds", "oddsAmerican", "americanOdds"):
        value = row.get(key)
        if isinstance(value, Mapping):
            value = value.get("american") or value.get("americanOdds") or value.get("display")
        if isinstance(value, str):
            text = value.strip().replace("−", "-")
            if re.fullmatch(r"[+-]?\d+", text):
                return int(text)
        elif isinstance(value, (int, float)):
            return int(value)
    for key in ("trueOdds", "oddsDecimal"):
        if row.get(key) is not None:
            return _american_from_decimal(row[key])
    raise DraftKingsPropSourceError("DK_SELECTION_PRICE_MISSING")


def _market_key(value: Any) -> str:
    key = re.sub(r"\s+", " ", str(value or "").lower().strip())
    key = re.sub(r"^(player|batter)\s+", "", key)
    key = re.sub(r"\s+(o/u|over\s*/\s*under|over under)$", "", key).strip()
    return key


def _canonical_market(name: Any, market_type: Any = None, subcategory: Any = None) -> str | None:
    for candidate in (name, market_type, subcategory):
        key = _market_key(candidate)
        if key in MARKET_LABELS:
            return MARKET_LABELS[key]
    return None


def _participant(selection: Mapping[str, Any], market: Mapping[str, Any]) -> str:
    participants = selection.get("participants")
    if isinstance(participants, list):
        for participant in participants:
            if isinstance(participant, Mapping):
                text = str(participant.get("name") or participant.get("fullName") or "").strip()
                if text:
                    return text
    for value in (
        selection.get("participant"),
        selection.get("participantName"),
        selection.get("name"),
        market.get("participant"),
    ):
        text = str(value or "").strip()
        if text and text.lower() not in {"over", "under", "yes", "no"}:
            text = re.sub(r"\s+(over|under|yes|no)\s+.*$", "", text, flags=re.I).strip()
            return text
    return ""


def _side(selection: Mapping[str, Any]) -> str | None:
    for value in (selection.get("label"), selection.get("outcomeType"), selection.get("outcome_type")):
        text = str(value or "").upper().strip()
        if text.startswith("OVER"):
            return "OVER"
        if text.startswith("UNDER"):
            return "UNDER"
        if text in {"YES", "NO"}:
            return text
    return None


def _event_id(selection: Mapping[str, Any], market: Mapping[str, Any], fallback: Any = None) -> str:
    for value in (
        selection.get("eventId"),
        selection.get("providerEventId"),
        market.get("eventId"),
        market.get("providerEventId"),
        fallback,
    ):
        text = str(value or "").strip()
        if text:
            return text
    raise DraftKingsPropSourceError("DK_EVENT_ID_MISSING")


def _line(selection: Mapping[str, Any], side: str) -> float:
    for key in ("points", "line"):
        if selection.get(key) is not None:
            return float(selection[key])
    if side in {"YES", "NO"}:
        return 0.5
    raise DraftKingsPropSourceError("DK_LINE_MISSING")


def _quote(
    *,
    selection: Mapping[str, Any],
    market: Mapping[str, Any],
    canonical: str,
    event_id: Any,
    now: datetime,
    raw_market_name: str,
) -> dict[str, Any]:
    participant = _participant(selection, market)
    side = _side(selection)
    if not participant:
        raise DraftKingsPropSourceError("DK_PARTICIPANT_MISSING")
    if side is None:
        raise DraftKingsPropSourceError("DK_SIDE_MISSING")
    line = _line(selection, side)
    if canonical in COUNT_MARKETS and side == "YES":
        side = "OVER"
    elif canonical in COUNT_MARKETS and side == "NO":
        side = "UNDER"
    return {
        "provider_event_id": _event_id(selection, market, event_id),
        "market": canonical,
        "entity_name": participant,
        "entity_name_normalized": normalize_name(participant),
        "side": side,
        "selection": str(selection.get("label") or side).strip(),
        "line": line,
        "american_odds": _selection_price(selection),
        "sportsbook": "DraftKings",
        "book_key": "draftkings_direct",
        "retrieved_at": now.isoformat(),
        "ttl_seconds": DEFAULT_TTL_SECONDS,
        "is_alternate": bool(market.get("isAlternate") or selection.get("isAlternate")),
        "raw_market_name": raw_market_name,
        "provider": "DRAFTKINGS_WEB_RESEARCH",
    }


def parse_category_payload(
    payload: Mapping[str, Any],
    *,
    event_id: int | str | None = None,
    retrieved_at: datetime | None = None,
) -> DraftKingsPropSnapshot:
    now = (retrieved_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    markets = payload.get("markets") or []
    selections = payload.get("selections") or []
    if not isinstance(markets, list) or not isinstance(selections, list):
        raise DraftKingsPropSourceError("DK_CATEGORY_SHAPE_INVALID")
    by_market: dict[str, list[Mapping[str, Any]]] = {}
    for selection in selections:
        if isinstance(selection, Mapping):
            market_id = str(selection.get("marketId") or selection.get("providerMarketId") or "")
            if market_id:
                by_market.setdefault(market_id, []).append(selection)
    quotes: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for market in markets:
        if not isinstance(market, Mapping):
            continue
        market_id = str(market.get("id") or market.get("marketId") or market.get("providerMarketId") or "")
        market_type = market.get("marketType") if isinstance(market.get("marketType"), Mapping) else {}
        canonical = _canonical_market(
            market.get("name") or market.get("label"),
            market_type.get("name") or market_type.get("label"),
        )
        if canonical is None:
            continue
        embedded = market.get("selections") or market.get("outcomes") or []
        rows: Iterable[Any] = embedded if isinstance(embedded, list) and embedded else by_market.get(market_id, [])
        raw_name = str(market.get("name") or market.get("label") or market_type.get("name") or "")
        for selection in rows:
            if not isinstance(selection, Mapping):
                continue
            try:
                quotes.append(
                    _quote(
                        selection=selection,
                        market=market,
                        canonical=canonical,
                        event_id=event_id,
                        now=now,
                        raw_market_name=raw_name,
                    )
                )
            except Exception as exc:
                failures.append(
                    {
                        "event_id": str(event_id or market.get("eventId") or ""),
                        "market_id": market_id,
                        "reason": f"{type(exc).__name__}:{exc}",
                    }
                )
    return DraftKingsPropSnapshot(tuple(quotes), tuple(failures))


def _flatten_offers(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _flatten_offers(item)


def _parse_v5_eventgroup(payload: Mapping[str, Any], *, retrieved_at: datetime | None = None) -> DraftKingsPropSnapshot:
    now = (retrieved_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    event_group = payload.get("eventGroup") if isinstance(payload.get("eventGroup"), Mapping) else payload
    categories = event_group.get("offerCategories") or []
    if not isinstance(categories, list):
        raise DraftKingsPropSourceError("DK_V5_OFFER_CATEGORIES_INVALID")
    quotes: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for category in categories:
        if not isinstance(category, Mapping):
            continue
        descriptors = category.get("offerSubcategoryDescriptors") or category.get("offerSubcategories") or []
        if not isinstance(descriptors, list):
            continue
        for descriptor in descriptors:
            if not isinstance(descriptor, Mapping):
                continue
            sub_name = descriptor.get("name")
            sub = descriptor.get("offerSubcategory") if isinstance(descriptor.get("offerSubcategory"), Mapping) else descriptor
            offers = sub.get("offers") or []
            for offer in _flatten_offers(offers):
                canonical = _canonical_market(offer.get("label") or offer.get("name"), sub_name)
                if canonical is None:
                    continue
                outcomes = offer.get("outcomes") or offer.get("selections") or []
                if not isinstance(outcomes, list):
                    continue
                raw_name = str(offer.get("label") or offer.get("name") or sub_name or "")
                for outcome in outcomes:
                    if not isinstance(outcome, Mapping):
                        continue
                    try:
                        quotes.append(
                            _quote(
                                selection=outcome,
                                market=offer,
                                canonical=canonical,
                                event_id=offer.get("eventId") or offer.get("providerEventId"),
                                now=now,
                                raw_market_name=raw_name,
                            )
                        )
                    except Exception as exc:
                        failures.append(
                            {
                                "event_id": str(offer.get("eventId") or offer.get("providerEventId") or ""),
                                "market_id": str(offer.get("id") or offer.get("providerOfferId") or ""),
                                "reason": f"{type(exc).__name__}:{exc}",
                            }
                        )
    return DraftKingsPropSnapshot(tuple(quotes), tuple(failures))


def _v5_urls(base: str, league_id: int) -> tuple[str, ...]:
    host = urlparse(base).netloc or "sportsbook-nash.draftkings.com"
    return (
        f"https://{host}/sites/US-SB/api/v5/eventgroups/{league_id}?format=json",
        f"https://{host}/sites/US-IL-SB/api/v5/eventgroups/{league_id}?format=json",
    )


def fetch_mlb_prop_quotes(*, opener: Callable = urlopen) -> DraftKingsPropSnapshot:
    home = _request(DK_HOME, opener=opener).decode("utf-8", errors="replace")
    base, league_id = _discover(home)
    league = _json(f"{base}v1/leagues/{league_id}", opener=opener)
    if not isinstance(league, Mapping):
        raise DraftKingsPropSourceError("DK_LEAGUE_SHAPE_INVALID")
    events = league.get("events")
    if not isinstance(events, list):
        raise DraftKingsPropSourceError("DK_LEAGUE_EVENTS_MISSING")

    all_quotes: list[dict[str, Any]] = []
    all_failures: list[dict[str, Any]] = []

    direct = parse_category_payload(league)
    all_quotes.extend(direct.quotes)
    all_failures.extend(direct.failures)

    if not all_quotes:
        for event in events:
            if not isinstance(event, Mapping):
                continue
            try:
                event_id = int(event["id"])
                cats = _json(f"{base}v1/events/{event_id}/categories", opener=opener)
                event_rows = cats.get("events") if isinstance(cats, Mapping) else None
                categories = (
                    ((event_rows or [{}])[0].get("categories") or [])
                    if isinstance(event_rows, list) and event_rows
                    else []
                )
                for category in categories:
                    if not isinstance(category, Mapping):
                        continue
                    name = str(category.get("name") or "").lower()
                    if not any(token in name for token in ("player", "batter", "pitcher", "hitting", "pitching")):
                        continue
                    category_id = category.get("id")
                    if category_id is None:
                        continue
                    snap = parse_category_payload(
                        _json(f"{base}v1/events/{event_id}/categories/{category_id}", opener=opener),
                        event_id=event_id,
                    )
                    all_quotes.extend(snap.quotes)
                    all_failures.extend(snap.failures)
            except Exception as exc:
                all_failures.append(
                    {"event_id": str(event.get("id") or ""), "reason": f"{type(exc).__name__}:{exc}"}
                )

    if not all_quotes:
        v5_errors: list[str] = []
        for url in _v5_urls(base, league_id):
            try:
                snap = _parse_v5_eventgroup(_json(url, opener=opener))
                all_quotes.extend(snap.quotes)
                all_failures.extend(snap.failures)
                if all_quotes:
                    break
            except Exception as exc:
                v5_errors.append(f"{type(exc).__name__}:{exc}")
        if not all_quotes:
            all_failures.append(
                {
                    "event_id": "",
                    "reason": "DraftKingsPropSourceError:DK_NO_RECOGNIZED_PROP_QUOTES",
                    "diagnostic": {
                        "league_event_count": len(events),
                        "league_keys": sorted(str(key) for key in league.keys()),
                        "v5_errors": v5_errors,
                    },
                }
            )

    return DraftKingsPropSnapshot(
        tuple(all_quotes),
        tuple(all_failures),
        league_id=league_id,
        base_url=base,
    )
