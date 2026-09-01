"""Canonical NFL live execution boundary for MANUAL/HYBRID/AUTOMATIC ingress.

Execution mode controls only how the frozen feature payload and raw sportsbook
snapshot arrive. Once those inputs exist, every mode enters the same canonical
M2 -> score distribution -> market readout/economics path.

This module deliberately does not promote markets or install Truth Gate floors.
The current NFL forward-selection contract remains shadow-only.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Mapping, Sequence

from sportsedge.core.clv.nfl_forward_capture import build_forward_decision_rows
from sportsedge.sports.nfl.m2 import NFLM2ScoreModel, derive_nfl_m2_score_distribution


class NFLExecutionMode(str, Enum):
    MANUAL = "MANUAL"
    HYBRID = "HYBRID"
    AUTOMATIC = "AUTOMATIC"


FeatureBuilder = Callable[[], Mapping[str, Any]]
OddsFetcher = Callable[[], Sequence[Mapping[str, Any]]]


def _dt(value: Any, error: str) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError(error)
    try:
        out = datetime.fromisoformat(raw[:-1] + "+00:00" if raw.endswith("Z") else raw)
    except ValueError as exc:
        raise ValueError(error) from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise ValueError(error)
    return out.astimezone(timezone.utc)


def _features(payload: Mapping[str, Any], captured_at: datetime) -> tuple[str, datetime, list[dict[str, Any]]]:
    if str(payload.get("sport") or "").lower() != "nfl":
        raise ValueError("NFL_LIVE_FEATURE_PAYLOAD_INVALID")
    source_hash = str(payload.get("source_manifest_sha256") or "").strip().lower()
    if len(source_hash) != 64 or any(ch not in "0123456789abcdef" for ch in source_hash):
        raise ValueError("NFL_LIVE_FEATURE_SOURCE_HASH_INVALID")
    asof = _dt(payload.get("asof_ts"), "NFL_LIVE_FEATURE_ASOF_INVALID")
    if asof > captured_at:
        raise ValueError("NFL_LIVE_FEATURE_FROM_FUTURE")
    games = payload.get("games")
    if not isinstance(games, list) or not games:
        raise ValueError("NFL_LIVE_FEATURE_GAMES_EMPTY")
    rows = []
    for row in games:
        if not isinstance(row, Mapping):
            raise ValueError("NFL_LIVE_FEATURE_GAME_INVALID")
        item = dict(row)
        if not str(item.get("game_id") or "").strip():
            raise ValueError("NFL_LIVE_FEATURE_GAME_ID_MISSING")
        rows.append(item)
    return source_hash, asof, rows


def _events(payload: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(payload, (str, bytes)) or not isinstance(payload, Sequence):
        raise ValueError("NFL_LIVE_ODDS_EVENTS_NOT_LIST")
    rows = [dict(row) for row in payload if isinstance(row, Mapping)]
    if len(rows) != len(payload):
        raise ValueError("NFL_LIVE_ODDS_EVENT_MALFORMED")
    return rows


def _event_for_game(game: Mapping[str, Any], events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    home = str(game.get("provider_home_team") or "").strip()
    away = str(game.get("provider_away_team") or "").strip()
    if not home or not away:
        raise ValueError("NFL_LIVE_PROVIDER_TEAM_IDENTITY_MISSING")
    start = _dt(game.get("game_start_ts"), "NFL_LIVE_GAME_START_INVALID")
    matches = []
    for event in events:
        if str(event.get("home_team") or "").strip() != home:
            continue
        if str(event.get("away_team") or "").strip() != away:
            continue
        try:
            event_start = _dt(event.get("commence_time"), "NFL_LIVE_EVENT_START_INVALID")
        except ValueError:
            continue
        if event_start == start:
            matches.append(dict(event))
    if len(matches) != 1:
        raise ValueError("NFL_LIVE_PROVIDER_EVENT_NOT_FOUND" if not matches else "NFL_LIVE_PROVIDER_EVENT_AMBIGUOUS")
    return matches[0]


def run_canonical_nfl_live(
    *,
    model: NFLM2ScoreModel,
    live_features: Mapping[str, Any],
    odds_events: Sequence[Mapping[str, Any]],
    captured_at: str | datetime,
    identity: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Run the shared NFL live core from already-frozen canonical inputs."""
    captured = _dt(captured_at, "NFL_LIVE_CAPTURE_TS_INVALID")
    source_hash, feature_asof, games = _features(live_features, captured)
    events = _events(odds_events)
    out: list[dict[str, Any]] = []
    for game in games:
        event = _event_for_game(game, events)
        distribution = derive_nfl_m2_score_distribution(model, game)
        rows = build_forward_decision_rows(
            game,
            event,
            distribution,
            captured_at=captured,
            identity=identity,
        )
        if len(rows) != 3:
            raise ValueError("NFL_LIVE_DECISION_MARKET_COUNT_INVALID")
        for row in rows:
            row["live_feature_source_manifest_sha256"] = source_hash
            row["live_feature_asof_ts"] = feature_asof.isoformat()
        out.extend(rows)
    return out


def run_nfl_live(
    *,
    mode: str | NFLExecutionMode,
    model: NFLM2ScoreModel,
    captured_at: str | datetime,
    identity: Mapping[str, Any],
    live_features: Mapping[str, Any] | None = None,
    odds_events: Sequence[Mapping[str, Any]] | None = None,
    feature_builder: FeatureBuilder | None = None,
    odds_fetcher: OddsFetcher | None = None,
) -> list[dict[str, Any]]:
    """Resolve mode-owned ingress and converge on :func:`run_canonical_nfl_live`.

    MANUAL: caller supplies frozen features and raw odds.
    HYBRID: caller supplies frozen features; odds acquisition is automatic.
    AUTOMATIC: both feature construction and odds acquisition are automatic.

    The callbacks are intentionally dependency-injected so tests can prove
    identical-input semantics without network access while production callers can
    bind the real feature builder/provider acquisition implementations.
    """
    if isinstance(mode, NFLExecutionMode):
        resolved = mode
    else:
        try:
            resolved = NFLExecutionMode(str(mode).upper())
        except ValueError as exc:
            raise ValueError("NFL_EXECUTION_MODE_INVALID") from exc

    if resolved is NFLExecutionMode.MANUAL:
        if live_features is None or odds_events is None:
            raise ValueError("NFL_MANUAL_INPUTS_REQUIRED")
        features = live_features
        odds = odds_events
    elif resolved is NFLExecutionMode.HYBRID:
        if live_features is None:
            raise ValueError("NFL_HYBRID_FEATURES_REQUIRED")
        if odds_fetcher is None:
            raise ValueError("NFL_HYBRID_ODDS_FETCHER_REQUIRED")
        features = live_features
        odds = odds_fetcher()
    else:
        if feature_builder is None:
            raise ValueError("NFL_AUTOMATIC_FEATURE_BUILDER_REQUIRED")
        if odds_fetcher is None:
            raise ValueError("NFL_AUTOMATIC_ODDS_FETCHER_REQUIRED")
        features = feature_builder()
        odds = odds_fetcher()

    return run_canonical_nfl_live(
        model=model,
        live_features=features,
        odds_events=odds,
        captured_at=captured_at,
        identity=identity,
    )
