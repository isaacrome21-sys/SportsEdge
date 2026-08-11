"""Automated MLB runner using native sportsbook acquisition.

This wrapper deliberately reuses run_auto_mlb for all modeling, feature, lineup,
TTL, deployment, and Truth Gate behavior. It only replaces the manual quote
snapshot URL with canonical quotes acquired from The Odds API after binding
provider games/players to exact MLB identity.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any, Callable, Mapping
from urllib.request import urlopen
from zoneinfo import ZoneInfo

from .auto_runner import AutoRunReport, run_auto_mlb
from .mlb_source import fetch_boxscore, fetch_schedule
from .odds_api_source import build_participant_index, fetch_mlb_player_prop_quotes

CHICAGO_TZ = ZoneInfo("America/Chicago")
MEMORY_QUOTES_URL = "https://sportsedge.local/native-odds"


class _MemoryResponse:
    def __init__(self, value: Any):
        self._raw = json.dumps(value, default=str).encode("utf-8")
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self):
        return self._raw


def _url(req: Any) -> str:
    return req if isinstance(req, str) else str(req.full_url)


def _roster_names(boxscore: Mapping[str, Any]) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for side in ("away", "home"):
        players = ((((boxscore.get("teams") or {}).get(side) or {}).get("players")) or {})
        if not isinstance(players, Mapping):
            continue
        for row in players.values():
            if not isinstance(row, Mapping):
                continue
            person = row.get("person") or {}
            try:
                player_id = int(person.get("id"))
            except (TypeError, ValueError):
                continue
            name = str(person.get("fullName") or "").strip()
            if player_id > 0 and name:
                out.append((player_id, name))
    return out


def run_auto_mlb_native_odds(
    *,
    odds_api_key: str,
    feature_url: str,
    projected_lineups_url: str | None = None,
    provider_token: str | None = None,
    now: datetime | None = None,
    opener: Callable = urlopen,
    registry_path: str = "config/deployments.json",
    require_confirmed_lineup: bool = False,
    min_edge: float = 0.0,
    kelly_multiplier: float = 0.25,
    bookmakers: tuple[str, ...] = ("draftkings",),
) -> AutoRunReport:
    current = now or datetime.now(timezone.utc)
    if not isinstance(current, datetime) or current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("NOW_TIMEZONE_REQUIRED")
    current = current.astimezone(timezone.utc)
    slate_date_ct = current.astimezone(CHICAGO_TZ).date().isoformat()

    schedule = fetch_schedule(slate_date_ct, opener=opener, now=current)
    roster_names: dict[int, list[tuple[int, str]]] = {}
    roster_failures: list[dict[str, Any]] = []
    for game in schedule:
        try:
            roster_names[game.game_pk] = _roster_names(fetch_boxscore(game.game_pk, opener=opener))
        except Exception as exc:
            roster_names[game.game_pk] = []
            roster_failures.append({"stage": "MLB_ROSTER_IDENTITY", "game_id": str(game.game_pk), "reason": f"{type(exc).__name__}: {exc}"})

    participant_index = build_participant_index(schedule=schedule, confirmed_names_by_game=roster_names)
    odds = fetch_mlb_player_prop_quotes(
        api_key=odds_api_key,
        schedule=schedule,
        participant_index=participant_index,
        opener=opener,
        bookmakers=bookmakers,
    )
    quote_payload = list(odds.quotes)

    def wrapped(req, timeout=15):
        if _url(req) == MEMORY_QUOTES_URL:
            return _MemoryResponse(quote_payload)
        return opener(req, timeout=timeout)

    report = run_auto_mlb(
        quote_url=MEMORY_QUOTES_URL,
        feature_url=feature_url,
        projected_lineups_url=projected_lineups_url,
        provider_token=provider_token,
        now=current,
        opener=wrapped,
        registry_path=registry_path,
        require_confirmed_lineup=require_confirmed_lineup,
        min_edge=min_edge,
        kelly_multiplier=kelly_multiplier,
    )
    acquisition_failures = [
        {"stage": "ODDS_API", **dict(item)} for item in odds.failures
    ] + roster_failures
    return AutoRunReport(
        report.slate_date_ct,
        report.generated_at_utc,
        report.run_status,
        report.results,
        tuple(acquisition_failures) + report.source_failures,
    )
