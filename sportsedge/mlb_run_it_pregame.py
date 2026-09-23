"""Unified public-source MLB RUN IT pregame acquisition bundle.

The bundle binds one game_pk to public MLB/Savant/NWS context plus optional
caller-supplied DraftKings quotes. Context and sportsbook prices remain outside
Model_P; native/manual DK quotes are normalized only for downstream HYBRID use.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.request import Request, urlopen

from .mlb_dk_hybrid_source import acquire_dk_hybrid_quotes
from .mlb_injury_scratch_source import acquire_injuries_and_scratches, confirmed_lineup_ids
from .mlb_park_venue_source import acquire_park_venue_context
from .mlb_statcast_preview_source import acquire_statcast_preview
from .mlb_umpire_source import acquire_umpire_context
from .mlb_weather_roof_source import acquire_weather_roof_context
from .source_lineage import canonical_json_sha256
from .statcast_daily_source import StatcastSnapshot

LIVE_FEED_BASE = "https://statsapi.mlb.com/api/v1.1/game"
SCHEMA_VERSION = "mlb_run_it_pregame_v2"
SOURCE = "MLB_PUBLIC_PREGAME_BUNDLE"


class MLBRunItPregameError(RuntimeError):
    pass


def live_feed_url(game_pk: int) -> str:
    return f"{LIVE_FEED_BASE}/{int(game_pk)}/feed/live"


def _open_live_feed(game_pk: int, *, opener: Callable = urlopen) -> dict[str, Any]:
    url = live_feed_url(game_pk)
    req = Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "SportsEdge-MLB-Pregame/2.0",
    })
    try:
        with opener(req, timeout=30) as response:
            raw = response.read()
    except Exception as exc:
        raise MLBRunItPregameError(f"LIVE_FEED_FETCH_FAILED:{url}") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise MLBRunItPregameError("LIVE_FEED_RESPONSE_NOT_JSON") from exc
    if not isinstance(payload, dict):
        raise MLBRunItPregameError("LIVE_FEED_RESPONSE_NOT_OBJECT")
    return payload


def _official_date(live_payload: Mapping[str, Any]) -> str | None:
    game_data = live_payload.get("gameData") or {}
    if not isinstance(game_data, Mapping):
        return None
    dt = game_data.get("datetime") or {}
    if isinstance(dt, Mapping) and dt.get("officialDate"):
        return str(dt["officialDate"])
    value = game_data.get("officialDate")
    return str(value) if value else None


def _probable_pitchers(live_payload: Mapping[str, Any]) -> dict[str, dict[str, Any] | None]:
    game_data = live_payload.get("gameData") or {}
    probable = game_data.get("probablePitchers") if isinstance(game_data, Mapping) else {}
    out: dict[str, dict[str, Any] | None] = {"away": None, "home": None}
    if not isinstance(probable, Mapping):
        return out
    for side in ("away", "home"):
        row = probable.get(side)
        if not isinstance(row, Mapping):
            continue
        try:
            player_id = int(row.get("id"))
        except (TypeError, ValueError):
            continue
        out[side] = {
            "player_id": player_id,
            "player_name": str(row.get("fullName") or "").strip() or None,
        }
    return out


def acquire_mlb_run_it_pregame(
    *,
    game_pk: int,
    as_of: datetime,
    opener: Callable = urlopen,
    include_statcast_html: bool = False,
    live_payload: Mapping[str, Any] | None = None,
    baseline_lineup_ids: Mapping[str, Any] | None = None,
    statcast_snapshot: StatcastSnapshot | None = None,
    umpire_history_rows: Iterable[Mapping[str, Any]] | None = None,
    umpire_prior_config: Mapping[str, Any] | None = None,
    venue_payload: Mapping[str, Any] | None = None,
    nws_points_payload: Mapping[str, Any] | None = None,
    nws_hourly_payload: Mapping[str, Any] | None = None,
    dk_quotes: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    live = dict(live_payload) if live_payload is not None else _open_live_feed(int(game_pk), opener=opener)
    day = _official_date(live)

    starters = {
        "status": "AVAILABLE" if any(_probable_pitchers(live).values()) else "MISSING",
        "probable_pitchers": _probable_pitchers(live),
        "model_p_eligible": False,
    }
    lineups = confirmed_lineup_ids(live)
    lineup_lane = {
        "status": "AVAILABLE" if any(lineups.values()) else "MISSING",
        "confirmed_lineup_ids": lineups,
        "model_p_eligible": False,
    }

    injuries = acquire_injuries_and_scratches(
        game_pk=int(game_pk),
        as_of=as_of,
        live_payload=live,
        opener=opener,
        baseline_lineup_ids=baseline_lineup_ids,
    )
    umpire = acquire_umpire_context(
        game_pk=int(game_pk),
        as_of=as_of,
        live_payload=live,
        official_date=day,
        opener=opener,
        history_rows=umpire_history_rows,
        prior_config=umpire_prior_config,
    )
    statcast = acquire_statcast_preview(
        game_pk=int(game_pk),
        as_of=as_of,
        live_payload=live,
        official_date=day,
        opener=opener,
        snapshot=statcast_snapshot,
        capture_html=bool(include_statcast_html),
    )
    park_venue = acquire_park_venue_context(
        game_pk=int(game_pk),
        as_of=as_of,
        live_payload=live,
        opener=opener,
        venue_payload=venue_payload,
    )
    weather_roof = acquire_weather_roof_context(
        game_pk=int(game_pk),
        as_of=as_of,
        park_venue=park_venue,
        live_payload=live,
        opener=opener,
        points_payload=nws_points_payload,
        hourly_payload=nws_hourly_payload,
    )
    hybrid_dk = acquire_dk_hybrid_quotes(quotes=dk_quotes, as_of=as_of)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "game_pk": int(game_pk),
        "as_of_utc": as_of.astimezone(timezone.utc).isoformat(),
        "official_date": day,
        "source": SOURCE,
        "starters": starters,
        "lineups": lineup_lane,
        "injuries_scratches": injuries,
        "umpire": umpire,
        "statcast": statcast,
        "park_venue": park_venue,
        "weather_roof": weather_roof,
        "hybrid_dk": hybrid_dk,
        "unimplemented_lanes": [],
        "model_p_eligible": False,
        "status": "AVAILABLE",
    }
    payload["payload_sha256"] = canonical_json_sha256(payload)
    return payload
