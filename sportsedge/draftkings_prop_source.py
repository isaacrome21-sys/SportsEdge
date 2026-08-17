"""Research-only direct DraftKings MLB player-prop acquisition.

This provider is intentionally isolated from production eligibility. It uses
DraftKings' public sportsbook web endpoints with no account credentials, records
provider provenance, and fails closed on response-shape surprises. It exists as a
fallback acquisition source for research/shadow use while paid provider capacity
is unavailable.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
from typing import Any, Callable, Mapping
from urllib.request import Request, urlopen

from .odds_api_source import normalize_name

DK_HOME = "https://sportsbook.draftkings.com/"
DEFAULT_TTL_SECONDS = 120

# Dynamic market-name mapping. DraftKings labels can change; unknown labels are
# skipped rather than guessed.
MARKET_LABELS = {
    "home runs": "HOME_RUNS",
    "hits": "HITS",
    "total bases": "TOTAL_BASES",
    "rbis": "RBI",
    "runs": "RUNS",
    "runs scored": "RUNS",
    "hits + runs + rbis": "HITS_RUNS_RBIS",
    "singles": "SINGLES",
    "doubles": "DOUBLES",
    "triples": "TRIPLES",
    "walks": "BATTER_BB",
    "strikeouts": "BATTER_K",
    "stolen bases": "STOLEN_BASES",
    "pitcher strikeouts": "PITCHER_K",
    "strikeouts thrown": "PITCHER_K",
    "hits allowed": "PITCHER_HITS_ALLOWED",
    "pitcher walks": "PITCHER_BB",
    "walks allowed": "PITCHER_BB",
    "earned runs allowed": "PITCHER_ER",
    "earned runs": "PITCHER_ER",
    "outs recorded": "PITCHER_OUTS",
}


class DraftKingsPropSourceError(RuntimeError):
    pass


@dataclass(frozen=True)
class DraftKingsPropSnapshot:
    quotes: tuple[dict[str, Any], ...]
    failures: tuple[dict[str, Any], ...]
    league_id: int | None = None
    base_url: str | None = None


def _request(url: str, *, opener: Callable = urlopen, timeout: int = 15) -> bytes:
    req = Request(url, headers={
        "Accept": "application/json,text/html,*/*",
        "User-Agent": "Mozilla/5.0 SportsEdge-DK-Research/1",
        "Referer": DK_HOME,
        "Origin": "https://sportsbook.draftkings.com",
    })
    with opener(req, timeout=timeout) as response:
        return response.read()


def _json(url: str, *, opener: Callable = urlopen) -> Any:
    raw = _request(url, opener=opener)
    try:
        return json.loads(raw)
    except Exception as exc:
        raise DraftKingsPropSourceError("DK_RESPONSE_NOT_JSON") from exc


def _discover(home_html: str) -> tuple[str, int]:
    # Public clients discover these values from homepage bootstrap state rather
    # than hard-coding an event-group id or sports-content host.
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

    sports = ((state.get("sports") or {}).get("data") or [])
    mlb_id = None
    for sport in sports:
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
    if dec >= 2.0:
        return int(round((dec - 1.0) * 100.0))
    return int(round(-100.0 / (dec - 1.0)))


def _selection_price(row: Mapping[str, Any]) -> int:
    for key in ("displayOdds", "oddsAmerican", "americanOdds"):
        value = row.get(key)
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


def _canonical_market(name: Any, market_type: Any = None) -> str | None:
    candidates = [str(name or ""), str(market_type or "")]
    for candidate in candidates:
        key = re.sub(r"\s+", " ", candidate.lower().strip())
        key = re.sub(r"^(player|batter)\s+", "", key)
        if key in MARKET_LABELS:
            return MARKET_LABELS[key]
    return None


def _participant(selection: Mapping[str, Any], market: Mapping[str, Any]) -> str:
    for value in (
        selection.get("participant"), selection.get("participantName"),
        selection.get("name"), market.get("participant"), market.get("name"),
    ):
        text = str(value or "").strip()
        if text and text.lower() not in {"over", "under", "yes", "no"}:
            # Strip common suffixes while preserving player name.
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


def parse_category_payload(payload: Mapping[str, Any], *, event_id: int, retrieved_at: datetime | None = None) -> DraftKingsPropSnapshot:
    now = (retrieved_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    markets = payload.get("markets") or []
    selections = payload.get("selections") or []
    if not isinstance(markets, list) or not isinstance(selections, list):
        raise DraftKingsPropSourceError("DK_CATEGORY_SHAPE_INVALID")

    by_market: dict[str, list[Mapping[str, Any]]] = {}
    for selection in selections:
        if not isinstance(selection, Mapping):
            continue
        market_id = str(selection.get("marketId") or "")
        if market_id:
            by_market.setdefault(market_id, []).append(selection)

    quotes: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for market in markets:
        if not isinstance(market, Mapping):
            continue
        market_id = str(market.get("id") or "")
        market_type = (market.get("marketType") or {}) if isinstance(market.get("marketType"), Mapping) else {}
        canonical = _canonical_market(market.get("name"), market_type.get("name"))
        if canonical is None:
            continue
        for selection in by_market.get(market_id, []):
            try:
                participant = _participant(selection, market)
                side = _side(selection)
                if not participant:
                    raise DraftKingsPropSourceError("DK_PARTICIPANT_MISSING")
                if side is None:
                    raise DraftKingsPropSourceError("DK_SIDE_MISSING")
                line = selection.get("points")
                if line is None and side in {"YES", "NO"}:
                    line = 0.5
                if line is None:
                    raise DraftKingsPropSourceError("DK_LINE_MISSING")
                quotes.append({
                    "provider_event_id": str(event_id),
                    "market": canonical,
                    "entity_name": participant,
                    "entity_name_normalized": normalize_name(participant),
                    "side": side,
                    "selection": str(selection.get("label") or side).strip(),
                    "line": float(line),
                    "american_odds": _selection_price(selection),
                    "sportsbook": "DraftKings",
                    "book_key": "draftkings_direct",
                    "retrieved_at": now.isoformat(),
                    "ttl_seconds": DEFAULT_TTL_SECONDS,
                    "is_alternate": bool(market.get("isAlternate") or selection.get("isAlternate")),
                    "raw_market_name": str(market.get("name") or market_type.get("name") or ""),
                    "provider": "DRAFTKINGS_WEB_RESEARCH",
                })
            except Exception as exc:
                failures.append({"event_id": str(event_id), "market_id": market_id, "reason": f"{type(exc).__name__}:{exc}"})
    return DraftKingsPropSnapshot(tuple(quotes), tuple(failures))


def fetch_mlb_prop_quotes(*, opener: Callable = urlopen) -> DraftKingsPropSnapshot:
    home = _request(DK_HOME, opener=opener).decode("utf-8", errors="replace")
    base, league_id = _discover(home)
    league = _json(f"{base}v1/leagues/{league_id}", opener=opener)
    events = league.get("events") if isinstance(league, Mapping) else None
    if not isinstance(events, list):
        raise DraftKingsPropSourceError("DK_LEAGUE_EVENTS_MISSING")

    all_quotes: list[dict[str, Any]] = []
    all_failures: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, Mapping):
            continue
        try:
            event_id = int(event["id"])
            cats = _json(f"{base}v1/events/{event_id}/categories", opener=opener)
            event_rows = cats.get("events") if isinstance(cats, Mapping) else None
            categories = ((event_rows or [{}])[0].get("categories") or []) if isinstance(event_rows, list) and event_rows else []
            for category in categories:
                if not isinstance(category, Mapping):
                    continue
                name = str(category.get("name") or "").lower()
                # Avoid downloading game lines/futures; player/pitcher categories only.
                if not any(token in name for token in ("player", "batter", "pitcher", "hitting", "pitching")):
                    continue
                category_id = category.get("id")
                if category_id is None:
                    continue
                payload = _json(f"{base}v1/events/{event_id}/categories/{category_id}", opener=opener)
                snap = parse_category_payload(payload, event_id=event_id)
                all_quotes.extend(snap.quotes)
                all_failures.extend(snap.failures)
        except Exception as exc:
            all_failures.append({"event_id": str(event.get("id") or ""), "reason": f"{type(exc).__name__}:{exc}"})
    return DraftKingsPropSnapshot(tuple(all_quotes), tuple(all_failures), league_id=league_id, base_url=base)
