"""Secret-safe raw CFB sportsbook acquisition for forward market evidence."""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Callable, Sequence
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sportsedge.odds_keyring import fetch_with_key_failover
from .forward_market_capture import validate_draftkings_snapshot

_BASE = "https://api.the-odds-api.com/v4"
_SPORT = "americanfootball_ncaaf"


@dataclass(frozen=True)
class CFBOddsPayload:
    raw: bytes
    payload: list[dict]


def build_cfb_odds_url() -> str:
    params = {
        "regions": "us",
        "bookmakers": "draftkings",
        "markets": "h2h,spreads,totals",
        "oddsFormat": "american",
        "dateFormat": "iso",
    }
    return f"{_BASE}/sports/{_SPORT}/odds?{urlencode(params)}"


def _http_fetch(url_without_key: str, key: str) -> CFBOddsPayload:
    url = f"{url_without_key}&{urlencode({'apiKey': key})}"
    try:
        with urlopen(
            Request(url, headers={"Accept": "application/json", "User-Agent": "SportsEdge-CFB-Forward/1"}),
            timeout=20,
        ) as response:
            raw = response.read()
    except HTTPError as exc:
        provider_code = ""
        try:
            body = json.loads(exc.read().decode("utf-8", errors="replace"))
            if isinstance(body, dict):
                provider_code = str(body.get("error_code") or body.get("code") or "").strip()
        except Exception:
            provider_code = ""
        detail = f"HTTP_{int(exc.code)}"
        if provider_code:
            detail += f":{provider_code}"
        raise RuntimeError(f"CFB_FORWARD_ODDS_FETCH_FAILED:{detail}") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("CFB_FORWARD_ODDS_RESPONSE_JSON_INVALID") from exc
    validate_draftkings_snapshot(payload)
    return CFBOddsPayload(raw=raw, payload=payload)


def fetch_cfb_odds(
    api_keys: Sequence[str],
    *,
    fetcher: Callable[[str, str], CFBOddsPayload] = _http_fetch,
):
    base = build_cfb_odds_url()
    result = fetch_with_key_failover(list(api_keys), lambda key: fetcher(base, key))
    validate_draftkings_snapshot(result.value.payload)
    return result
