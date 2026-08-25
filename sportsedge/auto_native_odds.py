"""Automated MLB runner using native sportsbook acquisition.

Default behavior uses the coherent joint MLB feature/engine path. An explicitly
supplied legacy feature_url retains the frozen compatibility path for callers that
still own that contract. Sportsbook prices never enter predictive features.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import json
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.request import urlopen
from zoneinfo import ZoneInfo

from .additional_mlb_odds_source import fetch_mlb_additional_quotes
from .auto_joint_runner import run_auto_joint_mlb
from .auto_runner import AutoRunReport, run_auto_mlb
from .edge_floors import DEFAULT_EDGE_FLOOR_CONFIG
from .game_odds_source import fetch_mlb_game_quotes
from .market_surface import DEFAULT_MARKET_SURFACE_PATH
from .mlb_history_cache import MLBHistoryCachedOpener
from .mlb_source import fetch_boxscore, fetch_schedule
from .odds_api_source import build_participant_index, fetch_mlb_player_prop_quotes
from .odds_keyring import fetch_with_key_failover

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


def _side_players(boxscore: Mapping[str, Any], side: str) -> list[tuple[int, str]]:
    out = []
    players = ((((boxscore.get("teams") or {}).get(side) or {}).get("players")) or {})
    if not isinstance(players, Mapping):
        return out
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


def _roster_names(boxscore: Mapping[str, Any]) -> list[tuple[int, str]]:
    return _side_players(boxscore, "away") + _side_players(boxscore, "home")


def run_auto_mlb_native_odds(
    *,
    odds_api_key: str,
    odds_api_keys: tuple[str, ...] = (),
    feature_url: str | None = None,
    projected_lineups_url: str | None = None,
    provider_token: str | None = None,
    now: datetime | None = None,
    opener: Callable = urlopen,
    registry_path: str = "config/deployments.json",
    require_confirmed_lineup: bool = False,
    edge_floor_config_path: str = DEFAULT_EDGE_FLOOR_CONFIG,
    kelly_multiplier: float = 0.25,
    bookmakers: tuple[str, ...] = ("draftkings",),
    history_cache_dir: str | Path | None = None,
    market_surface_path: str = DEFAULT_MARKET_SURFACE_PATH,
) -> AutoRunReport:
    current = now or datetime.now(timezone.utc)
    if not isinstance(current, datetime) or current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("NOW_TIMEZONE_REQUIRED")
    current = current.astimezone(timezone.utc)
    slate_date_ct = current.astimezone(CHICAGO_TZ).date().isoformat()

    schedule = fetch_schedule(slate_date_ct, opener=opener, now=current)
    roster_names = {}
    roster_failures = []
    for game in schedule:
        try:
            box = fetch_boxscore(game.game_pk, opener=opener)
            roster_names[game.game_pk] = _roster_names(box)
        except Exception as exc:
            roster_names[game.game_pk] = []
            roster_failures.append({
                "stage": "MLB_ROSTER_IDENTITY",
                "game_id": str(game.game_pk),
                "reason": f"{type(exc).__name__}: {exc}",
            })
    participant_index = build_participant_index(schedule=schedule, confirmed_names_by_game=roster_names)

    def fetch_all(key: str) -> dict[str, Any]:
        player = fetch_mlb_player_prop_quotes(
            api_key=key,
            schedule=schedule,
            participant_index=participant_index,
            opener=opener,
            bookmakers=bookmakers,
        )
        game = fetch_mlb_game_quotes(api_key=key, schedule=schedule, opener=opener, bookmakers=bookmakers)
        additional = fetch_mlb_additional_quotes(
            api_key=key,
            schedule=schedule,
            participant_index=participant_index,
            opener=opener,
            bookmakers=bookmakers,
        )
        return {
            "quotes": tuple(player.quotes) + tuple(game.quotes) + tuple(additional.quotes),
            "failures": (
                tuple({"surface": "PLAYER", **dict(x)} for x in player.failures)
                + tuple({"surface": "GAME", **dict(x)} for x in game.failures)
                + tuple({"surface": "ADDITIONAL", **dict(x)} for x in additional.failures)
            ),
        }

    keyring = fetch_with_key_failover((odds_api_key, *odds_api_keys), fetch_all)
    odds = keyring.value
    quote_payload = list(odds["quotes"])
    key_failures = [
        {"stage": "ODDS_API_KEY_FAILOVER", "key_slot": item.key_slot, "reason": item.reason}
        for item in keyring.failures
    ]
    acquisition_failures = (
        key_failures
        + [{"stage": "ODDS_API", **dict(item)} for item in odds["failures"]]
        + roster_failures
    )

    # Explicit legacy feature snapshots keep the old frozen path. The automatic
    # default (feature_url=None) is the coherent joint architecture.
    if feature_url is not None:
        def legacy_wrapped(req, timeout=15):
            if _url(req) == MEMORY_QUOTES_URL:
                return _MemoryResponse(quote_payload)
            return opener(req, timeout=timeout)

        report = run_auto_mlb(
            quote_url=MEMORY_QUOTES_URL,
            feature_url=feature_url,
            projected_lineups_url=projected_lineups_url,
            provider_token=provider_token,
            now=current,
            opener=legacy_wrapped,
            registry_path=registry_path,
            require_confirmed_lineup=require_confirmed_lineup,
            edge_floor_config_path=edge_floor_config_path,
            kelly_multiplier=kelly_multiplier,
            market_surface_path=market_surface_path,
        )
    else:
        history_opener = MLBHistoryCachedOpener(
            target_date=date.fromisoformat(slate_date_ct),
            cache_dir=history_cache_dir,
            opener=opener,
        )

        def joint_wrapped(req, timeout=15):
            if _url(req) == MEMORY_QUOTES_URL:
                return _MemoryResponse(quote_payload)
            return history_opener(req, timeout=timeout)

        report = run_auto_joint_mlb(
            quote_url=MEMORY_QUOTES_URL,
            projected_lineups_url=projected_lineups_url,
            provider_token=provider_token,
            now=current,
            opener=joint_wrapped,
            registry_path=registry_path,
            require_confirmed_lineup=require_confirmed_lineup,
            edge_floor_config_path=edge_floor_config_path,
            kelly_multiplier=kelly_multiplier,
            market_surface_path=market_surface_path,
        )

    return AutoRunReport(
        slate_date_ct=report.slate_date_ct,
        generated_at_utc=report.generated_at_utc,
        run_status=report.run_status,
        card_status=report.card_status,
        results=report.results,
        coverage_slots=report.coverage_slots,
        source_failures=tuple(acquisition_failures) + report.source_failures,
        market_surface_version=report.market_surface_version,
    )
