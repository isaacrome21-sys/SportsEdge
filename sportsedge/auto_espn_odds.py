"""MLB full-game fallback runner using ESPN scoreboard odds.

This lane is deliberately scoped to MONEYLINE/RUN_LINE/TOTALS. It keeps game
markets alive when metered Odds API capacity is unavailable while leaving player
props fail-closed until a separate prop provider is configured.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import json
from pathlib import Path
from typing import Any, Callable
from urllib.request import urlopen
from zoneinfo import ZoneInfo

from .auto_runner import AutoRunReport, run_auto_mlb
from .edge_floors import DEFAULT_EDGE_FLOOR_CONFIG
from .espn_game_odds_source import fetch_espn_mlb_game_quotes
from .mlb_generic_features import GAME_MARKETS, MLBGenericHistorySource
from .mlb_history_cache import MLBHistoryCachedOpener
from .mlb_source import fetch_schedule

CHICAGO_TZ = ZoneInfo("America/Chicago")
MEMORY_QUOTES_URL = "https://sportsedge.local/espn-game-odds"
MEMORY_FEATURES_URL = "https://sportsedge.local/espn-game-features"


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


def _official_date(game) -> date:
    value = game.official_date
    if not isinstance(value, str) or not value:
        raise ValueError("MLB_OFFICIAL_DATE_MISSING")
    return date.fromisoformat(value)


def run_auto_mlb_espn_game_odds(
    *,
    feature_url: str | None = None,
    projected_lineups_url: str | None = None,
    provider_token: str | None = None,
    now: datetime | None = None,
    opener: Callable = urlopen,
    registry_path: str = "config/deployments.json",
    require_confirmed_lineup: bool = True,
    edge_floor_config_path: str = DEFAULT_EDGE_FLOOR_CONFIG,
    kelly_multiplier: float = 0.25,
    history_cache_dir: str | Path | None = None,
) -> AutoRunReport:
    current = now or datetime.now(timezone.utc)
    if not isinstance(current, datetime) or current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("NOW_TIMEZONE_REQUIRED")
    current = current.astimezone(timezone.utc)
    slate_date_ct = current.astimezone(CHICAGO_TZ).date().isoformat()
    schedule = fetch_schedule(slate_date_ct, opener=opener, now=current)

    espn = fetch_espn_mlb_game_quotes(schedule=schedule, opener=opener, now=current)
    quote_payload = list(espn.quotes)
    native_features: list[dict[str, Any]] = []
    feature_failures: list[dict[str, Any]] = []
    selected_feature_url = feature_url

    if not selected_feature_url:
        selected_feature_url = MEMORY_FEATURES_URL
        history_opener = MLBHistoryCachedOpener(
            target_date=date.fromisoformat(slate_date_ct),
            cache_dir=history_cache_dir,
            opener=opener,
        )
        history = MLBGenericHistorySource(opener=history_opener, retrieved_at=current)
        schedule_by_pk = {int(game.game_pk): game for game in schedule}
        seen: set[tuple[int, str, str]] = set()
        for quote in quote_payload:
            market = str(quote.get("market"))
            try:
                if market not in GAME_MARKETS:
                    raise ValueError("ESPN_FALLBACK_NON_GAME_MARKET")
                game_pk = int(quote["game_id"])
                entity_id = str(quote["entity_id"])
                identity = (game_pk, entity_id, market)
                if identity in seen:
                    continue
                seen.add(identity)
                game = schedule_by_pk.get(game_pk)
                if game is None:
                    raise ValueError("MLB_FEATURE_GAME_NOT_FOUND")
                native_features.append(history.feature_row(
                    game_pk=game_pk,
                    market=market,
                    entity_id=entity_id,
                    target_date=_official_date(game),
                    away_team_id=int(game.away_id),
                    home_team_id=int(game.home_id),
                ))
            except Exception as exc:
                feature_failures.append({
                    "stage": "MLB_ESPN_FEATURE",
                    "market": market,
                    "game_id": str(quote.get("game_id", "UNKNOWN")),
                    "entity_id": str(quote.get("entity_id", "UNKNOWN")),
                    "reason": f"{type(exc).__name__}: {exc}",
                })

    def wrapped(req, timeout=15):
        url = _url(req)
        if url == MEMORY_QUOTES_URL:
            return _MemoryResponse(quote_payload)
        if url == MEMORY_FEATURES_URL:
            return _MemoryResponse(native_features)
        return opener(req, timeout=timeout)

    report = run_auto_mlb(
        quote_url=MEMORY_QUOTES_URL,
        feature_url=selected_feature_url,
        projected_lineups_url=projected_lineups_url,
        provider_token=provider_token,
        now=current,
        opener=wrapped,
        registry_path=registry_path,
        require_confirmed_lineup=require_confirmed_lineup,
        edge_floor_config_path=edge_floor_config_path,
        kelly_multiplier=kelly_multiplier,
    )
    acquisition_failures = [
        {"stage": "ESPN_GAME_ODDS", **dict(item)} for item in espn.failures
    ] + feature_failures + [{
        "stage": "PLAYER_PROP_PROVIDER",
        "reason": "ESPN_FALLBACK_SCOPED_TO_GAME_MARKETS; PLAYER_PROPS_NOT_ACQUIRED",
    }]
    return AutoRunReport(
        report.slate_date_ct,
        report.generated_at_utc,
        report.run_status,
        report.results,
        tuple(acquisition_failures) + report.source_failures,
    )
