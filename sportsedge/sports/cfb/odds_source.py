"""Raw-preserving CFB sportsbook acquisition for prospective market evidence.

This module performs no scheduling and makes no promotion claims. Callers receive
exact provider response bytes plus the parsed payload so those bytes can be
persisted and SHA256-bound by the CFB forward market-evidence contract.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Callable, Sequence
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sportsedge.odds_keyring import fetch_with_key_failover

_BASE = "https://api.the-odds-api.com/v4"
_SPORT = "americanfootball_ncaaf"


@dataclass(frozen=True)
class CFBForwardOddsSnapshot:
    raw: bytes
    payload: Any
    key_slot: int
    prior_key_failures: int


def _http_fetch(url_without_key: str, key: str) -> tuple[bytes, Any]:
    sep = "&" if "?" in url_without_key else "?"
    url = f"{url_without_key}{sep}{urlencode({'apiKey': key})}"
    try:
        with urlopen(
            Request(url, headers={"Accept": "application/json", "User-Agent": "SportsEdge-CFB-Forward/1"}),
            timeout=20,
        ) as response:
            raw = response.read()
    except HTTPError as exc:
        provider_code = ""
        try:
            payload = json.loads(exc.read().decode("utf-8", errors="replace"))
            if isinstance(payload, dict):
                provider_code = str(payload.get("error_code") or payload.get("code") or "").strip()
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
    return raw, payload


def build_cfb_odds_url(*, event_id: str | None = None) -> str:
    params = {
        "regions": "us",
        "bookmakers": "draftkings",
        "oddsFormat": "american",
        "dateFormat": "iso",
    }
    if event_id is not None:
        clean = str(event_id).strip()
        if not clean or "/" in clean:
            raise ValueError("CFB_FORWARD_EVENT_ID_INVALID")
        params["markets"] = "h2h,spreads,totals"
        return f"{_BASE}/sports/{_SPORT}/events/{clean}/odds?{urlencode(params)}"
    params["markets"] = "h2h,spreads,totals"
    return f"{_BASE}/sports/{_SPORT}/odds?{urlencode(params)}"


def fetch_cfb_odds(
    api_keys: Sequence[str],
    *,
    event_id: str | None = None,
    fetcher: Callable[[str, str], tuple[bytes, Any]] = _http_fetch,
) -> CFBForwardOddsSnapshot:
    """Fetch one untouched DraftKings CFB snapshot with credential failover."""
    base = build_cfb_odds_url(event_id=event_id)
    result = fetch_with_key_failover(list(api_keys), lambda key: fetcher(base, key))
    raw, payload = result.value
    if not isinstance(raw, bytes):
        raise ValueError("CFB_FORWARD_ODDS_RAW_BYTES_REQUIRED")
    if event_id is not None and not isinstance(payload, dict):
        raise ValueError("CFB_FORWARD_EVENT_ODDS_NOT_OBJECT")
    if event_id is None and not isinstance(payload, list):
        raise ValueError("CFB_FORWARD_SPORT_ODDS_NOT_LIST")
    return CFBForwardOddsSnapshot(
        raw=raw,
        payload=payload,
        key_slot=result.key_slot,
        prior_key_failures=len(result.failures),
    )
