"""Automated MLB runner using native sportsbook and hitter feature acquisition.

The wrapper deliberately reuses run_auto_mlb for all modeling, feature-bridge,
lineup, TTL, deployment, and Truth Gate behavior. When no external feature URL
is supplied, validated HITS and TOTAL_BASES features are reconstructed from
official MLB history. Unsupported native markets remain fail-closed.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import json
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.request import urlopen
from zoneinfo import ZoneInfo

from .auto_runner import AutoRunReport, run_auto_mlb
from .mlb_history_cache import MLBHistoryCachedOpener
from .mlb_hits_features import MLBHitsFeatureError, MLBHitsHistorySource
from .mlb_source import fetch_boxscore, fetch_schedule
from .mlb_total_bases_features import MLBTBFeatureError, MLBTBHistorySource
from .odds_api_source import build_participant_index, fetch_mlb_player_prop_quotes
from .odds_keyring import fetch_with_key_failover

CHICAGO_TZ = ZoneInfo("America/Chicago")
MEMORY_QUOTES_URL = "https://sportsedge.local/native-odds"
MEMORY_FEATURES_URL = "https://sportsedge.local/native-features"


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
    out: list[tuple[int, str]] = []
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


def _player_team_index(*, game, boxscore: Mapping[str, Any]) -> dict[int, tuple[int, int]]:
    out: dict[int, tuple[int, int]] = {}
    sides = (
        ("away", int(game.away_id), game.home_probable_pitcher_id),
        ("home", int(game.home_id), game.away_probable_pitcher_id),
    )
    for side, team_id, opponent_pitcher in sides:
        if opponent_pitcher is None:
            continue
        for player_id, _ in _side_players(boxscore, side):
            if player_id in out and out[player_id] != (team_id, int(opponent_pitcher)):
                raise ValueError("MLB_ROSTER_PLAYER_AMBIGUOUS")
            out[player_id] = (team_id, int(opponent_pitcher))
    return out


def _official_date(game) -> date:
    value = game.official_date
    if not isinstance(value, str) or not value:
        raise ValueError("MLB_OFFICIAL_DATE_MISSING")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("MLB_OFFICIAL_DATE_INVALID") from exc


def _fetch_odds_snapshot(*, key: str, schedule, participant_index, opener, bookmakers):
    snapshot = fetch_mlb_player_prop_quotes(
        api_key=key,
        schedule=schedule,
        participant_index=participant_index,
        opener=opener,
        bookmakers=bookmakers,
    )
    # A provider key that can list events but cannot fetch any event-level odds
    # is not a successful acquisition. Force keyring failover without treating a
    # legitimate zero-prop slate (no provider fetch failures) as an error.
    fetch_failures = [
        item for item in snapshot.failures
        if str(item.get("reason", "")).startswith("ODDS_API_FETCH_FAILED:")
    ]
    if not snapshot.quotes and fetch_failures:
        raise RuntimeError(f"ODDS_API_ZERO_QUOTES_WITH_FETCH_FAILURES:{len(fetch_failures)}")
    return snapshot


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
    player_teams: dict[int, dict[int, tuple[int, int]]] = {}
    roster_failures: list[dict[str, Any]] = []
    for game in schedule:
        try:
            box = fetch_boxscore(game.game_pk, opener=opener)
            roster_names[game.game_pk] = _roster_names(box)
            player_teams[game.game_pk] = _player_team_index(game=game, boxscore=box)
        except Exception as exc:
            roster_names[game.game_pk] = []
            player_teams[game.game_pk] = {}
            roster_failures.append({"stage": "MLB_ROSTER_IDENTITY", "game_id": str(game.game_pk), "reason": f"{type(exc).__name__}: {exc}"})

    participant_index = build_participant_index(schedule=schedule, confirmed_names_by_game=roster_names)
    keyring = fetch_with_key_failover(
        (odds_api_key, *odds_api_keys),
        lambda key: _fetch_odds_snapshot(
            key=key,
            schedule=schedule,
            participant_index=participant_index,
            opener=opener,
            bookmakers=bookmakers,
        ),
    )
    odds = keyring.value
    key_failures = [
        {"stage": "ODDS_API_KEY_FAILOVER", "key_slot": item.key_slot, "reason": item.reason}
        for item in keyring.failures
    ]
    quote_payload = list(odds.quotes)

    native_feature_failures: list[dict[str, Any]] = []
    native_features: list[dict[str, Any]] = []
    selected_feature_url = feature_url
    if not selected_feature_url:
        selected_feature_url = MEMORY_FEATURES_URL
        history_opener = MLBHistoryCachedOpener(
            target_date=date.fromisoformat(slate_date_ct),
            cache_dir=history_cache_dir,
            opener=opener,
        )
        hits_history = MLBHitsHistorySource(opener=history_opener, retrieved_at=current)
        tb_history = MLBTBHistorySource(opener=history_opener, retrieved_at=current)
        schedule_by_pk = {int(game.game_pk): game for game in schedule}
        seen: set[tuple[int, int, str]] = set()
        for quote in quote_payload:
            market = str(quote.get("market"))
            if market not in {"HITS", "TOTAL_BASES"}:
                continue
            try:
                game_pk = int(quote["game_id"])
                player_id = int(quote["entity_id"])
                identity = (game_pk, player_id, market)
                if identity in seen:
                    continue
                seen.add(identity)
                game = schedule_by_pk.get(game_pk)
                if game is None:
                    raise ValueError("MLB_FEATURE_GAME_NOT_FOUND")
                binding = (player_teams.get(game_pk) or {}).get(player_id)
                if binding is None:
                    raise ValueError("MLB_FEATURE_PLAYER_TEAM_UNRESOLVED")
                team_id, starter_id = binding
                if market == "HITS":
                    native_features.append(hits_history.feature_envelope(
                        game_pk=game_pk,
                        team_id=team_id,
                        target_date=_official_date(game),
                        batter_id=player_id,
                        starter_id=starter_id,
                    ))
                else:
                    if game.venue_id is None:
                        raise MLBTBFeatureError("VENUE_UNMAPPED", {"venue_id": None, "game_pk": game_pk})
                    native_features.append(tb_history.feature_envelope(
                        game_pk=game_pk,
                        team_id=team_id,
                        target_date=_official_date(game),
                        batter_id=player_id,
                        starter_id=starter_id,
                        venue_id=int(game.venue_id),
                    ))
            except Exception as exc:
                stage = "MLB_HITS_FEATURE" if market == "HITS" else "MLB_TOTAL_BASES_FEATURE"
                native_feature_failures.append({
                    "stage": stage,
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
        min_edge=min_edge,
        kelly_multiplier=kelly_multiplier,
    )
    acquisition_failures = key_failures + [
        {"stage": "ODDS_API", **dict(item)} for item in odds.failures
    ] + roster_failures + native_feature_failures
    return AutoRunReport(
        report.slate_date_ct,
        report.generated_at_utc,
        report.run_status,
        report.results,
        tuple(acquisition_failures) + report.source_failures,
    )
