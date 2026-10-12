"""MLB pitch-level tracking acquisition via the official MLB StatsAPI.

Source: ``https://statsapi.mlb.com/api/v1.1/game/{gamePk}/feed/live``

This is the same documented StatsAPI family already used for schedule and
history acquisition (see ``mlb_v7_statsapi_history``); MLB publishes public
API docs for it at https://statsapi.mlb.com/docs. The game feed carries
per-pitch Statcast-derived tracking inside ``liveData.plays.allPlays[].playEvents[]``
as ``pitchData``: release speed, spin rate/direction, break shape, extension,
plate location, and full trajectory coordinates.

Acquisition layer only -- it returns per-pitcher per-game aggregates and never
prices anything. Consumers must enforce point-in-time discipline: only games
whose ``detailedState`` is ``Final`` are accepted, and only games completed
before the decision ``as_of`` may feed a snapshot. Live/in-progress games are
out of scope for this module (live pricing is a separate phase).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen

SOURCE = "MLB_STATSAPI_PITCH_TRACKING"
SCHEMA_VERSION = "mlb_statsapi_pitch_tracking_v1"
FEED_URL = "https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"
# Slim the ~700KB feed to the sections this module parses (~16KB observed).
FIELDS = (
    "gameData,game,pk,datetime,officialDate,status,detailedState,"
    "liveData,plays,allPlays,about,atBatIndex,inning,"
    "matchup,pitcher,id,fullName,batter,id,fullName,batSide,pitchHand,"
    "playEvents,isPitch,details,pitchData"
)
REQUIRED_PITCHDATA_KEYS = frozenset({"startSpeed", "endSpeed"})


class PitchTrackingError(RuntimeError):
    pass


def _fail(code: str) -> PitchTrackingError:
    return PitchTrackingError(f"PITCH_TRACKING_{code}")


def _to_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out and out not in (float("inf"), float("-inf")) else None


def _to_int(value: Any) -> int | None:
    f = _to_float(value)
    return int(f) if f is not None else None


@dataclass(frozen=True)
class PitchEvent:
    game_pk: int
    official_date: str
    inning: int | None
    at_bat_index: int | None
    pitcher_id: int
    pitcher_name: str | None
    batter_id: int | None
    pitch_type: str | None
    start_speed: float | None
    end_speed: float | None
    spin_rate: float | None
    spin_direction: float | None
    break_angle: float | None
    break_length: float | None
    extension: float | None
    zone: int | None


@dataclass(frozen=True)
class PitcherGameTracking:
    game_pk: int
    official_date: str
    pitcher_id: int
    pitcher_name: str | None
    n_pitches: int
    avg_start_speed: float | None
    max_start_speed: float | None
    avg_end_speed: float | None
    avg_spin_rate: float | None
    avg_break_length: float | None
    avg_extension: float | None
    pitch_mix: tuple[tuple[str, int], ...]


def _request_json(url: str, *, opener: Callable = urlopen, timeout: int = 60) -> Any:
    import json

    req = Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "SportsEdge-PitchTracking/1.0",
    })
    try:
        with opener(req, timeout=timeout) as response:
            raw = response.read()
    except Exception as exc:
        raise _fail(f"FETCH_FAILED:{type(exc).__name__}") from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise _fail("RESPONSE_NOT_JSON") from exc


def _parse_pitch_event(
    game_pk: int,
    official_date: str,
    play: Mapping[str, Any],
    event: Mapping[str, Any],
) -> PitchEvent | None:
    if not event.get("isPitch"):
        return None
    pitch_data = event.get("pitchData")
    if not isinstance(pitch_data, Mapping):
        return None
    matchup = play.get("matchup") if isinstance(play.get("matchup"), Mapping) else {}
    pitcher = matchup.get("pitcher") if isinstance(matchup.get("pitcher"), Mapping) else {}
    pitcher_id = _to_int(pitcher.get("id"))
    if pitcher_id is None:
        return None
    batter = matchup.get("batter") if isinstance(matchup.get("batter"), Mapping) else {}
    details = event.get("details") if isinstance(event.get("details"), Mapping) else {}
    pitch_type = details.get("type") if isinstance(details.get("type"), Mapping) else {}
    breaks = pitch_data.get("breaks") if isinstance(pitch_data.get("breaks"), Mapping) else {}
    about = play.get("about") if isinstance(play.get("about"), Mapping) else {}
    return PitchEvent(
        game_pk=game_pk,
        official_date=official_date,
        inning=_to_int(about.get("inning")),
        at_bat_index=_to_int(about.get("atBatIndex")),
        pitcher_id=pitcher_id,
        pitcher_name=pitcher.get("fullName"),
        batter_id=_to_int(batter.get("id")),
        pitch_type=pitch_type.get("description"),
        start_speed=_to_float(pitch_data.get("startSpeed")),
        end_speed=_to_float(pitch_data.get("endSpeed")),
        spin_rate=_to_float(breaks.get("spinRate")),
        spin_direction=_to_float(breaks.get("spinDirection")),
        break_angle=_to_float(breaks.get("breakAngle")),
        break_length=_to_float(breaks.get("breakLength")),
        extension=_to_float(pitch_data.get("extension")),
        zone=_to_int(pitch_data.get("zone")),
    )


def fetch_game_pitch_tracking(
    game_pk: int,
    *,
    opener: Callable = urlopen,
    timeout: int = 60,
) -> dict[str, Any]:
    """Fetch and normalize pitch-level tracking for one completed MLB game.

    Fail-closed: raises PitchTrackingError with an explicit reason code when
    the game is not Final, the feed shape is unexpected, or the fetch fails.
    """
    try:
        pk = int(game_pk)
    except (TypeError, ValueError) as exc:
        raise _fail("GAME_PK_INVALID") from exc
    url = FEED_URL.format(game_pk=pk) + "?" + urlencode({"fields": FIELDS})
    payload = _request_json(url, opener=opener, timeout=timeout)
    if not isinstance(payload, Mapping):
        raise _fail("FEED_NOT_OBJECT")
    game_data = payload.get("gameData")
    if not isinstance(game_data, Mapping):
        raise _fail("GAMEDATA_MISSING")
    status = game_data.get("status") if isinstance(game_data.get("status"), Mapping) else {}
    detailed = str(status.get("detailedState") or "")
    if detailed != "Final":
        raise _fail(f"GAME_NOT_FINAL:{detailed or 'UNKNOWN'}")
    official_date = str((game_data.get("datetime") or {}).get("officialDate") or "")
    live = payload.get("liveData")
    plays = (live.get("plays") or {}).get("allPlays") if isinstance(live, Mapping) else None
    if not isinstance(plays, list) or not plays:
        raise _fail("NO_PLAYS")
    events: list[PitchEvent] = []
    skipped_no_pitchdata = 0
    for play in plays:
        if not isinstance(play, Mapping):
            continue
        for event in play.get("playEvents") or []:
            if not isinstance(event, Mapping):
                continue
            if event.get("isPitch") and not isinstance(event.get("pitchData"), Mapping):
                skipped_no_pitchdata += 1
                continue
            parsed = _parse_pitch_event(pk, official_date, play, event)
            if parsed is not None:
                events.append(parsed)
    if not events:
        raise _fail("NO_PITCH_EVENTS")
    return {
        "schema_version": SCHEMA_VERSION,
        "source": SOURCE,
        "game_pk": pk,
        "official_date": official_date,
        "detailed_state": detailed,
        "pitch_events": events,
        "skipped_no_pitchdata": skipped_no_pitchdata,
    }


def _mean(values: Iterable[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), 4) if vals else None


def aggregate_pitcher_game(pitch_events: Iterable[PitchEvent]) -> list[PitcherGameTracking]:
    """Aggregate normalized pitch events to one row per pitcher per game."""
    events = list(pitch_events)
    if not events:
        raise _fail("NO_PITCH_EVENTS")
    by_pitcher: dict[int, list[PitchEvent]] = {}
    for event in events:
        by_pitcher.setdefault(event.pitcher_id, []).append(event)
    out: list[PitcherGameTracking] = []
    for pitcher_id in sorted(by_pitcher):
        rows = by_pitcher[pitcher_id]
        mix: dict[str, int] = {}
        for row in rows:
            if row.pitch_type:
                mix[row.pitch_type] = mix.get(row.pitch_type, 0) + 1
        speeds = [r.start_speed for r in rows if r.start_speed is not None]
        out.append(PitcherGameTracking(
            game_pk=rows[0].game_pk,
            official_date=rows[0].official_date,
            pitcher_id=pitcher_id,
            pitcher_name=rows[0].pitcher_name,
            n_pitches=len(rows),
            avg_start_speed=_mean(speeds),
            max_start_speed=round(max(speeds), 2) if speeds else None,
            avg_end_speed=_mean(r.end_speed for r in rows),
            avg_spin_rate=_mean(r.spin_rate for r in rows),
            avg_break_length=_mean(r.break_length for r in rows),
            avg_extension=_mean(r.extension for r in rows),
            pitch_mix=tuple(sorted(mix.items())),
        ))
    return out
