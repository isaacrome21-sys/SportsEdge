"""Reusable raw NFL sportsbook acquisition for live/forward execution.

Provider data remains untouched. This module owns request construction,
credential failover, and response-shape validation so CLI/workflow and future
AUTOMATIC mode callers share one acquisition implementation.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Sequence
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sportsedge.odds_keyring import fetch_with_key_failover

_BASE = "https://api.the-odds-api.com/v4"
_SPORT = "americanfootball_nfl"


def _http_fetch(url_without_key: str, key: str) -> Any:
    sep = "&" if "?" in url_without_key else "?"
    url = f"{url_without_key}{sep}{urlencode({'apiKey': key})}"
    with urlopen(
        Request(url, headers={"Accept": "application/json", "User-Agent": "SportsEdge-NFL-Forward/1"}),
        timeout=20,
    ) as response:
        raw = response.read()
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("NFL_FORWARD_ODDS_RESPONSE_JSON_INVALID") from exc


def build_nfl_odds_url(*, event_id: str | None = None) -> str:
    params = {
        "regions": "us",
        "bookmakers": "draftkings",
        "oddsFormat": "american",
        "dateFormat": "iso",
    }
    if event_id is not None:
        clean = str(event_id).strip()
        if not clean or "/" in clean:
            raise ValueError("NFL_FORWARD_EVENT_ID_INVALID")
        params["markets"] = "h2h,spreads,totals,alternate_spreads,alternate_totals"
        return f"{_BASE}/sports/{_SPORT}/events/{clean}/odds?{urlencode(params)}"
    params["markets"] = "h2h,spreads,totals"
    return f"{_BASE}/sports/{_SPORT}/odds?{urlencode(params)}"


def fetch_nfl_odds(
    api_keys: Sequence[str],
    *,
    event_id: str | None = None,
    fetcher: Callable[[str, str], Any] = _http_fetch,
):
    """Fetch one untouched provider snapshot with key failover.

    Returns the existing keyring result object so callers retain key-slot and
    prior-failure provenance without exposing credential values.
    """
    base = build_nfl_odds_url(event_id=event_id)
    result = fetch_with_key_failover(list(api_keys), lambda key: fetcher(base, key))
    payload = result.value
    if event_id is not None and not isinstance(payload, dict):
        raise ValueError("NFL_FORWARD_EVENT_ODDS_NOT_OBJECT")
    if event_id is None and not isinstance(payload, list):
        raise ValueError("NFL_FORWARD_SPORT_ODDS_NOT_LIST")
    return result
