"""Automatic Baseball Savant / Statcast pregame context.

Public sources only:
- Baseball Savant Statcast CSV search (already used by statcast_daily_source)
- Baseball Savant Game Preview URL as durable provenance
- Optional preview HTML capture for the same page a human would open

This module never scrapes a paid product and never writes sportsbook prices.
Rolling windows are exclusive of the current MLB local date so today's game
cannot leak into the feature snapshot.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Callable, Iterable, Mapping
from urllib.request import Request, urlopen

from .mlb_source import SAVANT_PREVIEW_BASE
from .source_lineage import canonical_json_sha256
from .statcast_daily_source import (
    SOURCE as STATCAST_SOURCE,
    StatcastSnapshot,
    fetch_daily_statcast,
)

SCHEMA_VERSION = "mlb_statcast_preview_source_v1"
PREVIEW_SOURCE = "BASEBALL_SAVANT_GAME_PREVIEW"


class MLBStatcastPreviewError(RuntimeError):
    pass


def preview_url(game_pk: int, official_date: str | None = None) -> str:
    url = f"{SAVANT_PREVIEW_BASE}?game_pk={int(game_pk)}"
    if official_date:
        try:
            day = date.fromisoformat(str(official_date)[:10])
        except ValueError:
            return url
        url += f"&game_date={day.strftime('%m/%d/%Y')}"
    return url


def _player_ids_from_live(live_payload: Mapping[str, Any]) -> dict[str, list[int]]:
    game_data = live_payload.get("gameData") or {}
    players = game_data.get("players") if isinstance(game_data, Mapping) else {}
    batters: list[int] = []
    pitchers: list[int] = []
    if isinstance(players, Mapping):
        for row in players.values():
            if not isinstance(row, Mapping):
                continue
            try:
                pid = int(row.get("id"))
            except (TypeError, ValueError):
                continue
            primary = ((row.get("primaryPosition") or {}).get("abbreviation") or "").upper()
            if primary == "P":
                pitchers.append(pid)
            else:
                batters.append(pid)

    # Probable pitchers live under gameData and can be available before the
    # boxscore/lineups exist. Do not make them conditional on liveData.boxscore.
    probable_pitchers = game_data.get("probablePitchers") if isinstance(game_data, Mapping) else {}
    if isinstance(probable_pitchers, Mapping):
        for side in ("away", "home"):
            probable = probable_pitchers.get(side)
            if isinstance(probable, Mapping) and probable.get("id"):
                try:
                    pitchers.append(int(probable["id"]))
                except (TypeError, ValueError):
                    continue

    box = ((live_payload.get("liveData") or {}).get("boxscore") or {}).get("teams") or {}
    if isinstance(box, Mapping):
        for side in ("away", "home"):
            team = box.get(side) or {}
            for raw_id in team.get("battingOrder") or []:
                try:
                    batters.append(int(raw_id))
                except (TypeError, ValueError):
                    continue
    return {
        "batters": sorted(set(batters)),
        "pitchers": sorted(set(pitchers)),
    }


def _index_rows(rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        entity_id = str(row.get("entity_id") or "").strip()
        if entity_id:
            out[entity_id] = dict(row)
    return out


def hitter_context(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "entity_id": row.get("entity_id"),
        "xwoba_contact": row.get("xwoba_contact"),
        "xba_contact": row.get("xba_contact"),
        "xslg_contact": row.get("xslg_contact"),
        "barrel_pct": row.get("barrel_rate"),
        "hard_hit_pct": row.get("hard_hit_rate"),
        "avg_exit_velocity": row.get("avg_exit_velocity"),
        "avg_launch_angle": row.get("avg_launch_angle"),
        "k_per_pa": row.get("k_per_pa"),
        "bb_per_pa": row.get("bb_per_pa"),
        "hr_per_pa": row.get("hr_per_pa"),
        "vs_l_pa": row.get("vs_l_pa"),
        "vs_r_pa": row.get("vs_r_pa"),
        "pa": row.get("pa"),
        "window_start": row.get("window_start"),
        "window_end": row.get("window_end"),
    }


def pitcher_context(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "entity_id": row.get("entity_id"),
        "xwoba_contact_allowed": row.get("xwoba_contact"),
        "xba_contact_allowed": row.get("xba_contact"),
        "xslg_contact_allowed": row.get("xslg_contact"),
        "barrel_pct_allowed": row.get("barrel_rate"),
        "hard_hit_pct_allowed": row.get("hard_hit_rate"),
        "avg_exit_velocity_allowed": row.get("avg_exit_velocity"),
        "avg_launch_angle_allowed": row.get("avg_launch_angle"),
        "k_per_pa": row.get("k_per_pa"),
        "bb_per_pa": row.get("bb_per_pa"),
        "avg_release_speed": row.get("avg_release_speed"),
        "max_release_speed": row.get("max_release_speed"),
        "vs_l_pa": row.get("vs_l_pa"),
        "vs_r_pa": row.get("vs_r_pa"),
        "pa": row.get("pa"),
        "window_start": row.get("window_start"),
        "window_end": row.get("window_end"),
    }


def capture_preview_html(
    game_pk: int,
    *,
    official_date: str | None = None,
    opener: Callable = urlopen,
) -> dict[str, Any]:
    url = preview_url(game_pk, official_date)
    req = Request(url, headers={
        "Accept": "text/html,*/*",
        "User-Agent": "SportsEdge-Statcast-Preview/1.0",
        "Referer": "https://baseballsavant.mlb.com/",
    })
    try:
        with opener(req, timeout=30) as response:
            raw = response.read()
    except Exception as exc:
        return {
            "status": "SOURCE_FAILED",
            "source": PREVIEW_SOURCE,
            "url": url,
            "error": type(exc).__name__,
            "byte_length": 0,
        }
    text = raw.decode("utf-8", errors="replace") if raw else ""
    return {
        "status": "AVAILABLE" if text.strip() else "EMPTY",
        "source": PREVIEW_SOURCE,
        "url": url,
        "byte_length": len(raw or b""),
        "has_statcast_tokens": any(
            token in text.lower()
            for token in ("xwoba", "exit velocity", "barrel", "statcast", "launch angle")
        ),
    }


def bind_snapshot_to_game(
    snapshot: StatcastSnapshot,
    *,
    live_payload: Mapping[str, Any],
) -> dict[str, Any]:
    ids = _player_ids_from_live(live_payload)
    batters = _index_rows(snapshot.batter_rows)
    pitchers = _index_rows(snapshot.pitcher_rows)
    bound_hitters = {
        str(pid): hitter_context(batters.get(str(pid)))
        for pid in ids["batters"]
        if str(pid) in batters
    }
    bound_pitchers = {
        str(pid): pitcher_context(pitchers.get(str(pid)))
        for pid in ids["pitchers"]
        if str(pid) in pitchers
    }
    return {
        "hitters": bound_hitters,
        "pitchers": bound_pitchers,
        "requested_hitter_ids": ids["batters"],
        "requested_pitcher_ids": ids["pitchers"],
        "bound_hitter_count": len(bound_hitters),
        "bound_pitcher_count": len(bound_pitchers),
    }


def acquire_statcast_preview(
    *,
    game_pk: int,
    as_of: datetime,
    live_payload: Mapping[str, Any] | None = None,
    official_date: str | None = None,
    opener: Callable = urlopen,
    days: int = 30,
    snapshot: StatcastSnapshot | None = None,
    capture_html: bool = False,
) -> dict[str, Any]:
    live_payload = live_payload or {}
    if snapshot is None:
        snapshot = fetch_daily_statcast(days=days, opener=opener, now=as_of)
    bound = bind_snapshot_to_game(snapshot, live_payload=live_payload)
    preview = (
        capture_preview_html(int(game_pk), official_date=official_date, opener=opener)
        if capture_html else {"status": "SKIPPED", "url": preview_url(int(game_pk), official_date)}
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "game_pk": int(game_pk),
        "as_of_utc": as_of.astimezone(timezone.utc).isoformat(),
        "source": STATCAST_SOURCE,
        "preview_source": PREVIEW_SOURCE,
        "preview_url": preview_url(int(game_pk), official_date),
        "window_start": snapshot.start_date,
        "window_end": snapshot.end_date,
        "retrieved_at": snapshot.retrieved_at,
        "raw_pitch_rows": snapshot.raw_pitch_rows,
        "preview": preview,
        "matchup": bound,
        "model_p_eligible": False,
        "status": "AVAILABLE" if (bound["bound_hitter_count"] or bound["bound_pitcher_count"] or snapshot.raw_pitch_rows) else "MISSING",
    }
    payload["payload_sha256"] = canonical_json_sha256(payload)
    return payload
