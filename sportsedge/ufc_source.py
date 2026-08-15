"""Live UFC data sources for SportsEdge.

The module is deliberately dependency-light and fail-closed. UFCStats is used for
fight/fighter statistics; live prices come from The Odds API compatible MMA feeds.
Raw sportsbook prices never enter the fighter feature vector.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
import json
import re
from typing import Callable, Iterable, Mapping, Sequence
from urllib.parse import urlencode
from urllib.request import Request, urlopen

UFCSTATS_BASE = "http://ufcstats.com"
ODDS_API_BASE = "https://api.the-odds-api.com/v4"


class UFCSourceError(RuntimeError):
    pass


@dataclass(frozen=True)
class BoutListing:
    event: str
    event_date: str
    bout_url: str
    fighter_a: str
    fighter_b: str
    weight_class: str
    rounds: int


@dataclass(frozen=True)
class FighterProfile:
    name: str
    fighter_url: str
    height_in: float | None
    reach_in: float | None
    stance: str
    dob: str | None
    slpm: float
    sapm: float
    str_acc: float
    str_def: float
    td_avg: float
    td_acc: float
    td_def: float
    sub_avg: float


@dataclass(frozen=True)
class OddsQuote:
    event_id: str
    commence_time: str
    home_team: str
    away_team: str
    bookmaker: str
    market: str
    selection: str
    price: int
    point: float | None = None
    retrieved_at: str = ""


def _get_text(url: str, *, opener: Callable = urlopen, timeout: int = 20) -> str:
    req = Request(url, headers={"User-Agent": "SportsEdge/1.0"})
    try:
        with opener(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as exc:  # pragma: no cover - network wrapper
        raise UFCSourceError(f"FETCH_FAILED {url}: {type(exc).__name__}: {exc}") from exc


def _strip_html(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    value = unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def _pct(text: str) -> float:
    text = text.strip().replace("%", "")
    if not text or text == "--":
        return 0.0
    return float(text) / 100.0


def _num(text: str) -> float:
    text = text.strip()
    if not text or text == "--":
        return 0.0
    return float(text)


def _inches(text: str) -> float | None:
    m = re.search(r"(\d+)\s*'\s*(\d+)\s*\"", text)
    if m:
        return float(int(m.group(1)) * 12 + int(m.group(2)))
    m = re.search(r"(\d+(?:\.\d+)?)\s*\"", text)
    return float(m.group(1)) if m else None


def completed_event_urls(*, opener: Callable = urlopen) -> list[str]:
    html = _get_text(f"{UFCSTATS_BASE}/statistics/events/completed?page=all", opener=opener)
    urls = re.findall(r'href="(http://ufcstats\.com/event-details/[^"]+)"', html)
    # preserve order and remove duplicate first featured row
    return list(dict.fromkeys(urls))


def upcoming_event_urls(*, opener: Callable = urlopen) -> list[str]:
    html = _get_text(f"{UFCSTATS_BASE}/statistics/events/upcoming?page=all", opener=opener)
    urls = re.findall(r'href="(http://ufcstats\.com/event-details/[^"]+)"', html)
    return list(dict.fromkeys(urls))


def parse_event(url: str, *, opener: Callable = urlopen) -> list[BoutListing]:
    html = _get_text(url, opener=opener)
    name_match = re.search(r'<span class="b-content__title-highlight">\s*([^<]+)', html)
    date_match = re.search(r'DATE:\s*</i>\s*([^<]+)', html)
    event = _strip_html(name_match.group(1)) if name_match else url.rsplit("/", 1)[-1]
    event_date = _strip_html(date_match.group(1)) if date_match else ""
    rows = re.findall(r'<tr[^>]+data-link="([^"]+)"[^>]*>(.*?)</tr>', html, flags=re.S)
    out: list[BoutListing] = []
    for bout_url, row in rows:
        fighters = [_strip_html(x) for x in re.findall(r'<a[^>]+href="http://ufcstats\.com/fighter-details/[^"]+"[^>]*>(.*?)</a>', row, flags=re.S)]
        if len(fighters) < 2:
            continue
        cells = [_strip_html(x) for x in re.findall(r'<td[^>]*>(.*?)</td>', row, flags=re.S)]
        weight_class = next((c for c in cells if "weight" in c.lower() or c in {"Flyweight", "Bantamweight", "Featherweight", "Lightweight", "Welterweight", "Middleweight", "Light Heavyweight", "Heavyweight", "Women’s Strawweight", "Women’s Flyweight", "Women’s Bantamweight"}), "")
        rounds = 5 if any(token in event.lower() for token in ("title",)) else 3
        out.append(BoutListing(event, event_date, bout_url, fighters[0], fighters[1], weight_class, rounds))
    return out


def parse_fighter_profile(url: str, *, opener: Callable = urlopen) -> FighterProfile:
    html = _get_text(url, opener=opener)
    name_match = re.search(r'<span class="b-content__title-highlight">\s*([^<]+)', html)
    name = _strip_html(name_match.group(1)) if name_match else url.rsplit("/", 1)[-1]
    def field(label: str) -> str:
        m = re.search(rf'{re.escape(label)}:\s*</i>\s*([^<]+)', html, flags=re.I)
        return _strip_html(m.group(1)) if m else ""
    return FighterProfile(
        name=name,
        fighter_url=url,
        height_in=_inches(field("HEIGHT")),
        reach_in=_inches(field("REACH")),
        stance=field("STANCE"),
        dob=field("DOB") or None,
        slpm=_num(field("SLpM")),
        sapm=_num(field("SApM")),
        str_acc=_pct(field("Str. Acc.")),
        str_def=_pct(field("Str. Def")),
        td_avg=_num(field("TD Avg.")),
        td_acc=_pct(field("TD Acc.")),
        td_def=_pct(field("TD Def.")),
        sub_avg=_num(field("Sub. Avg.")),
    )


def fighter_urls_from_bout(bout_url: str, *, opener: Callable = urlopen) -> tuple[str, str]:
    html = _get_text(bout_url, opener=opener)
    urls = re.findall(r'href="(http://ufcstats\.com/fighter-details/[^"]+)"', html)
    unique = list(dict.fromkeys(urls))
    if len(unique) < 2:
        raise UFCSourceError("BOUT_FIGHTER_URLS_MISSING")
    return unique[0], unique[1]


def fetch_live_mma_odds(*, api_key: str, bookmakers: Sequence[str] = ("draftkings",),
                        markets: Sequence[str] = ("h2h",), regions: str = "us",
                        opener: Callable = urlopen) -> list[OddsQuote]:
    if not api_key:
        raise UFCSourceError("ODDS_API_KEY_MISSING")
    params = urlencode({
        "apiKey": api_key,
        "regions": regions,
        "markets": ",".join(markets),
        "bookmakers": ",".join(bookmakers),
        "oddsFormat": "american",
        "dateFormat": "iso",
    })
    url = f"{ODDS_API_BASE}/sports/mma_mixed_martial_arts/odds/?{params}"
    raw = _get_text(url, opener=opener)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise UFCSourceError("ODDS_JSON_INVALID") from exc
    if not isinstance(payload, list):
        raise UFCSourceError("ODDS_PAYLOAD_INVALID")
    now = datetime.now(timezone.utc).isoformat()
    out: list[OddsQuote] = []
    for event in payload:
        if not isinstance(event, Mapping):
            continue
        for book in event.get("bookmakers") or []:
            if not isinstance(book, Mapping):
                continue
            for market in book.get("markets") or []:
                if not isinstance(market, Mapping):
                    continue
                key = str(market.get("key") or "")
                for outcome in market.get("outcomes") or []:
                    if not isinstance(outcome, Mapping):
                        continue
                    try:
                        price = int(outcome.get("price"))
                    except (TypeError, ValueError):
                        continue
                    point = outcome.get("point")
                    out.append(OddsQuote(
                        event_id=str(event.get("id") or ""),
                        commence_time=str(event.get("commence_time") or ""),
                        home_team=str(event.get("home_team") or ""),
                        away_team=str(event.get("away_team") or ""),
                        bookmaker=str(book.get("key") or ""),
                        market=key,
                        selection=str(outcome.get("name") or ""),
                        price=price,
                        point=float(point) if isinstance(point, (int, float)) else None,
                        retrieved_at=now,
                    ))
    return out


def normalize_name(name: str) -> str:
    value = unescape(name).lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def pair_h2h_quotes(quotes: Iterable[OddsQuote]) -> list[tuple[OddsQuote, OddsQuote]]:
    grouped: dict[tuple[str, str], list[OddsQuote]] = {}
    for q in quotes:
        if q.market != "h2h":
            continue
        grouped.setdefault((q.event_id, q.bookmaker), []).append(q)
    pairs: list[tuple[OddsQuote, OddsQuote]] = []
    for items in grouped.values():
        if len(items) == 2:
            pairs.append((items[0], items[1]))
    return pairs
