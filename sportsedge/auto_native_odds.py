"""Automated MLB runner using native sportsbook and Hits feature acquisition.

The wrapper reuses run_auto_mlb for all modeling, lineup, TTL, deployment, and
Truth Gate behavior. Provider games/players are first bound to exact MLB
identity. When no external feature URL is configured, only the validated HITS
feature contract is built natively from strictly-prior MLB history; unsupported
native markets remain missing-feature blocked rather than guessed.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.request import urlopen
from zoneinfo import ZoneInfo

from .auto_runner import AutoRunReport, run_auto_mlb
from .mlb_hits_features import JsonHistoryCache, build_hits_feature_envelope
from .mlb_source import fetch_boxscore, fetch_schedule
from .odds_api_source import build_participant_index, fetch_mlb_player_prop_quotes

CHICAGO_TZ = ZoneInfo("America/Chicago")
MEMORY_QUOTES_URL = "https://sportsedge.local/native-odds"
MEMORY_FEATURES_URL = "https://sportsedge.local/native-features"


class NativeFeatureBindingError(RuntimeError):
    pass


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


def _player_side(boxscore: Mapping[str, Any], player_id: int) -> str:
    matches: list[str] = []
    for side in ("away", "home"):
        players = ((((boxscore.get("teams") or {}).get(side) or {}).get("players")) or {})
        if not isinstance(players, Mapping):
            continue
        for row in players.values():
            if not isinstance(row, Mapping):
                continue
            person = row.get("person") or {}
            try:
                pid = int(person.get("id"))
            except (TypeError, ValueError):
                continue
            if pid == player_id:
                matches.append(side)
                break
    if len(matches) != 1:
        raise NativeFeatureBindingError(
            "NATIVE_HITS_PLAYER_GAME_BINDING_MISSING" if not matches
            else "NATIVE_HITS_PLAYER_GAME_BINDING_AMBIGUOUS"
        )
    return matches[0]


def _native_hits_features(
    *, quote_payload: list[dict[str, Any]], schedule, boxscores: Mapping[int, Mapping[str, Any]],
    current: datetime, opener: Callable, cache: JsonHistoryCache | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    games = {int(g.game_pk): g for g in schedule}
    features: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    for quote in quote_payload:
        if str(quote.get("market")) != "HITS":
            continue
        try:
            game_pk = int(quote["game_id"])
            player_id = int(quote["entity_id"])
        except (KeyError, TypeError, ValueError) as exc:
            failures.append({"stage": "NATIVE_HITS_FEATURES", "reason": "NATIVE_HITS_QUOTE_IDENTITY_MALFORMED"})
            continue
        identity = (game_pk, player_id)
        if identity in seen:
            continue
        seen.add(identity)
        try:
            game = games.get(game_pk)
            if game is None:
                raise NativeFeatureBindingError("NATIVE_HITS_GAME_NOT_FOUND")
            box = boxscores.get(game_pk)
            if box is None:
                raise NativeFeatureBindingError("NATIVE_HITS_BOXSCORE_UNAVAILABLE")
            side = _player_side(box, player_id)
            if side == "away":
                team_id = int(game.away_id)
                starter_id = game.home_probable_pitcher_id
            else:
                team_id = int(game.home_id)
                starter_id = game.away_probable_pitcher_id
            if starter_id is None:
                raise NativeFeatureBindingError("NATIVE_HITS_OPPOSING_STARTER_MISSING")
            official_date = game.official_date
            if not official_date:
                raise NativeFeatureBindingError("NATIVE_HITS_OFFICIAL_DATE_MISSING")
            features.append(build_hits_feature_envelope(
                game_pk=game_pk, game_date=official_date, batter_id=player_id,
                starter_id=int(starter_id), team_id=team_id, retrieved_at=current,
                opener=opener, cache=cache,
            ))
        except Exception as exc:
            failures.append({
                "stage": "NATIVE_HITS_FEATURES", "game_id": str(game_pk),
                "player_id": str(player_id), "market": "HITS",
                "reason": f"{type(exc).__name__}: {exc}",
            })
    return features, failures


def run_auto_mlb_native_odds(
    *,
    odds_api_key: str,
    feature_url: str | None = None,
    projected_lineups_url: str | None = None,
    provider_token: str | None = None,
    now: datetime | None = None,
    opener: Callable = urlopen,
    registry_path: str = "config/deployments.json",
    require_confirmed_lineup: bool = False,
    min_edge: float = 0.0,
    kelly_multiplier: float = 0.25,
    bookmakers: tuple[str, ...] = ("draftkings",),
    history_cache_dir: str | Path | None = None,
) -> AutoRunReport:
    current = now or datetime.now(timezone.utc)
    if not isinstance(current, datetime) or current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("NOW_TIMEZONE_REQUIRED")
    current = current.astimezone(timezone.utc)
    slate_date_ct = current.astimezone(CHICAGO_TZ).date().isoformat()

    schedule = fetch_schedule(slate_date_ct, opener=opener, now=current)
    roster_names: dict[int, list[tuple[int, str]]] = {}
    boxscores: dict[int, Mapping[str, Any]] = {}
    roster_failures: list[dict[str, Any]] = []
    for game in schedule:
        try:
            box = fetch_boxscore(game.game_pk, opener=opener)
            boxscores[game.game_pk] = box
            roster_names[game.game_pk] = _roster_names(box)
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

    native_feature_failures: list[dict[str, Any]] = []
    native_feature_payload: list[dict[str, Any]] = []
    effective_feature_url = (feature_url or "").strip()
    if not effective_feature_url:
        cache = JsonHistoryCache(history_cache_dir)
        native_feature_payload, native_feature_failures = _native_hits_features(
            quote_payload=quote_payload, schedule=schedule, boxscores=boxscores,
            current=current, opener=opener, cache=cache,
        )
        effective_feature_url = MEMORY_FEATURES_URL

    def wrapped(req, timeout=15):
        url = _url(req)
        if url == MEMORY_QUOTES_URL:
            return _MemoryResponse(quote_payload)
        if url == MEMORY_FEATURES_URL:
            return _MemoryResponse(native_feature_payload)
        return opener(req, timeout=timeout)

    report = run_auto_mlb(
        quote_url=MEMORY_QUOTES_URL,
        feature_url=effective_feature_url,
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
    ] + roster_failures + native_feature_failures
    return AutoRunReport(
        report.slate_date_ct,
        report.generated_at_utc,
        report.run_status,
        report.results,
        tuple(acquisition_failures) + report.source_failures,
    )
