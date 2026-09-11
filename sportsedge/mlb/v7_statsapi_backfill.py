from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen


STATSAPI_BASE = "https://statsapi.mlb.com"
ALLOWED_GAME_TYPES = frozenset({"R", "F", "D", "L", "W"})
SOURCE_ROOT_NOTE = "evidence/mlb_v8_replay_sources"


class V7StatsAPIBackfillError(RuntimeError):
    pass


@dataclass(frozen=True)
class FinalGame:
    game_id: int
    game_start_time: str
    home_team_id: int
    away_team_id: int
    venue_id: int
    game_type: str


def _iso_utc(value: Any, code: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise V7StatsAPIBackfillError(code)
    try:
        dt = datetime.fromisoformat(raw[:-1] + "+00:00" if raw.endswith("Z") else raw)
    except ValueError as exc:
        raise V7StatsAPIBackfillError(code) from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise V7StatsAPIBackfillError(code)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _int(value: Any, code: str) -> int:
    if isinstance(value, bool):
        raise V7StatsAPIBackfillError(code)
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise V7StatsAPIBackfillError(code) from exc


def _json_get(url: str, *, attempts: int = 4, timeout: int = 30) -> dict[str, Any]:
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            req = Request(url, headers={"User-Agent": "SportsEdge-V7-Backfill/1.0"})
            with urlopen(req, timeout=timeout) as response:  # nosec B310 - frozen HTTPS host assembled below
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict):
                raise V7StatsAPIBackfillError("STATSAPI_JSON_OBJECT_REQUIRED")
            return payload
        except Exception as exc:  # network/HTTP/JSON all retry, then fail closed
            last = exc
            if attempt + 1 < attempts:
                time.sleep(min(2 ** attempt, 8))
    raise V7StatsAPIBackfillError(f"STATSAPI_FETCH_FAILED:{url}") from last


def schedule_url(start_date: str, end_date: str) -> str:
    query = urlencode({
        "sportId": 1,
        "gameTypes": ",".join(sorted(ALLOWED_GAME_TYPES)),
        "startDate": start_date,
        "endDate": end_date,
        "hydrate": "venue,team",
    })
    return f"{STATSAPI_BASE}/api/v1/schedule?{query}"


def feed_url(game_id: int) -> str:
    return f"{STATSAPI_BASE}/api/v1.1/game/{int(game_id)}/feed/live"


def venue_url(venue_id: int) -> str:
    return f"{STATSAPI_BASE}/api/v1/venues/{int(venue_id)}"


def parse_final_games(schedule: Mapping[str, Any]) -> list[FinalGame]:
    games: list[FinalGame] = []
    for date_row in schedule.get("dates") or []:
        if not isinstance(date_row, Mapping):
            continue
        for row in date_row.get("games") or []:
            if not isinstance(row, Mapping):
                continue
            game_type = str(row.get("gameType") or "")
            if game_type not in ALLOWED_GAME_TYPES:
                continue
            status = row.get("status") or {}
            abstract = str(status.get("abstractGameState") or "") if isinstance(status, Mapping) else ""
            if abstract != "Final":
                continue
            teams = row.get("teams") or {}
            venue = row.get("venue") or {}
            try:
                games.append(FinalGame(
                    game_id=_int(row.get("gamePk"), "GAME_ID_MISSING"),
                    game_start_time=_iso_utc(row.get("gameDate"), "GAME_START_TIME_INVALID"),
                    home_team_id=_int(teams["home"]["team"]["id"], "HOME_TEAM_ID_MISSING"),
                    away_team_id=_int(teams["away"]["team"]["id"], "AWAY_TEAM_ID_MISSING"),
                    venue_id=_int(venue.get("id"), "VENUE_ID_MISSING"),
                    game_type=game_type,
                ))
            except (KeyError, TypeError) as exc:
                raise V7StatsAPIBackfillError("FINAL_GAME_IDENTITY_INCOMPLETE") from exc
    by_id = {g.game_id: g for g in games}
    if len(by_id) != len(games):
        raise V7StatsAPIBackfillError("DUPLICATE_GAME_ID_IN_SCHEDULE")
    return sorted(games, key=lambda g: (g.game_start_time, g.game_id))


def _final_at(feed: Mapping[str, Any]) -> str:
    live = feed.get("liveData") or {}
    plays = live.get("plays") or {} if isinstance(live, Mapping) else {}
    all_plays = plays.get("allPlays") or [] if isinstance(plays, Mapping) else []
    end_times: list[str] = []
    for play in all_plays:
        if not isinstance(play, Mapping):
            continue
        about = play.get("about") or {}
        if isinstance(about, Mapping) and about.get("endTime"):
            end_times.append(_iso_utc(about["endTime"], "PLAY_END_TIME_INVALID"))
    if not end_times:
        current = plays.get("currentPlay") or {} if isinstance(plays, Mapping) else {}
        about = current.get("about") or {} if isinstance(current, Mapping) else {}
        if isinstance(about, Mapping) and about.get("endTime"):
            end_times.append(_iso_utc(about["endTime"], "PLAY_END_TIME_INVALID"))
    if not end_times:
        raise V7StatsAPIBackfillError("FINAL_AT_UNAVAILABLE")
    return max(end_times)


def _team_bullpen_rows(
    *,
    game: FinalGame,
    feed: Mapping[str, Any],
    side: str,
    team_id: int,
    final_at: str,
) -> list[dict[str, Any]]:
    live = feed.get("liveData") or {}
    box = live.get("boxscore") or {} if isinstance(live, Mapping) else {}
    teams = box.get("teams") or {} if isinstance(box, Mapping) else {}
    team_box = teams.get(side) or {} if isinstance(teams, Mapping) else {}
    if not isinstance(team_box, Mapping):
        raise V7StatsAPIBackfillError(f"BOXSCORE_TEAM_MISSING:{game.game_id}:{side}")
    pitcher_order = team_box.get("pitchers")
    players = team_box.get("players")
    if not isinstance(pitcher_order, list) or not pitcher_order or not isinstance(players, Mapping):
        raise V7StatsAPIBackfillError(f"PITCHER_ORDER_MISSING:{game.game_id}:{side}")

    # StatsAPI boxscore pitcher order is appearance order. The first pitcher is the
    # realized starter; only subsequent appearances are eligible for bullpen usage.
    rows: list[dict[str, Any]] = []
    for raw_pitcher_id in pitcher_order[1:]:
        pitcher_id = _int(raw_pitcher_id, "PITCHER_ID_INVALID")
        player = players.get(f"ID{pitcher_id}") or players.get(str(pitcher_id))
        if not isinstance(player, Mapping):
            raise V7StatsAPIBackfillError(f"PITCHER_STATS_MISSING:{game.game_id}:{pitcher_id}")
        stats = player.get("stats") or {}
        pitching = stats.get("pitching") or {} if isinstance(stats, Mapping) else {}
        if not isinstance(pitching, Mapping) or pitching.get("numberOfPitches") is None:
            raise V7StatsAPIBackfillError(f"PITCH_COUNT_MISSING:{game.game_id}:{pitcher_id}")
        rows.append({
            "game_id": game.game_id,
            "team_id": team_id,
            "pitcher_id": pitcher_id,
            "pitches": _int(pitching.get("numberOfPitches"), "PITCH_COUNT_INVALID"),
            "game_start_time": game.game_start_time,
            "final_at": final_at,
        })
    return rows


def parse_feed(game: FinalGame, feed: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    final_at = _final_at(feed)
    if final_at < game.game_start_time:
        raise V7StatsAPIBackfillError(f"FINAL_BEFORE_START:{game.game_id}")
    history = [
        {
            "game_id": game.game_id,
            "team_id": game.away_team_id,
            "venue_id": game.venue_id,
            "game_start_time": game.game_start_time,
            "status": "Final",
            "final_at": final_at,
        },
        {
            "game_id": game.game_id,
            "team_id": game.home_team_id,
            "venue_id": game.venue_id,
            "game_start_time": game.game_start_time,
            "status": "Final",
            "final_at": final_at,
        },
    ]
    bullpen = _team_bullpen_rows(
        game=game, feed=feed, side="away", team_id=game.away_team_id, final_at=final_at
    ) + _team_bullpen_rows(
        game=game, feed=feed, side="home", team_id=game.home_team_id, final_at=final_at
    )
    return history, bullpen


def parse_venue(venue_id: int, payload: Mapping[str, Any]) -> dict[str, Any]:
    venues = payload.get("venues")
    if not isinstance(venues, list) or len(venues) != 1 or not isinstance(venues[0], Mapping):
        raise V7StatsAPIBackfillError(f"VENUE_PAYLOAD_INVALID:{venue_id}")
    row = venues[0]
    location = row.get("location") or {}
    coords = location.get("defaultCoordinates") or {} if isinstance(location, Mapping) else {}
    tz = row.get("timeZone") or {}
    try:
        latitude = float(coords["latitude"])
        longitude = float(coords["longitude"])
        timezone_id = str(tz["id"]).strip()
    except (KeyError, TypeError, ValueError) as exc:
        raise V7StatsAPIBackfillError(f"VENUE_FIXED_FACTS_MISSING:{venue_id}") from exc
    if not timezone_id or not (-90 <= latitude <= 90) or not (-180 <= longitude <= 180):
        raise V7StatsAPIBackfillError(f"VENUE_FIXED_FACTS_INVALID:{venue_id}")
    return {
        "venue_id": int(venue_id),
        "latitude": latitude,
        "longitude": longitude,
        "timezone": timezone_id,
    }


def _canonical_jsonl(rows: Iterable[Mapping[str, Any]], sort_key: Callable[[Mapping[str, Any]], Any]) -> bytes:
    ordered = sorted((dict(r) for r in rows), key=sort_key)
    return b"".join(
        (json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
        for row in ordered
    )


def _write_bytes(path: Path, payload: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def _write_manifest(
    *,
    root: Path,
    source_class: str,
    coverage_start: str,
    coverage_end: str,
    fields: list[str],
    semantics: dict[str, Any],
    evidence_rel: str,
    evidence_sha: str,
    row_count: int,
    source_uri: str,
) -> None:
    manifest = {
        "schema_version": 1,
        "source_class": source_class,
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
        "fields": fields,
        "semantics": semantics,
        "evidence_files": [{"path": evidence_rel, "sha256": evidence_sha}],
        "rows": row_count,
        "source_uri": source_uri,
        "backfill_policy_id": "MLB_V7_FEATURE_BACKFILL_POLICY_V1",
        "promotion_authority": False,
        "model_p_authority": False,
    }
    path = root / "attestations" / f"{source_class}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def acquire(
    *,
    start_date: str,
    end_date: str,
    output_root: Path,
    workers: int = 8,
    fetch_json: Callable[[str], dict[str, Any]] = _json_get,
) -> dict[str, Any]:
    schedule_source = schedule_url(start_date, end_date)
    schedule = fetch_json(schedule_source)
    games = parse_final_games(schedule)
    if not games:
        raise V7StatsAPIBackfillError("NO_FINAL_MLB_GAMES_IN_COVERAGE")

    history_rows: list[dict[str, Any]] = []
    bullpen_rows: list[dict[str, Any]] = []

    def fetch_game(game: FinalGame) -> tuple[int, list[dict[str, Any]], list[dict[str, Any]]]:
        history, bullpen = parse_feed(game, fetch_json(feed_url(game.game_id)))
        return game.game_id, history, bullpen

    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        future_map = {pool.submit(fetch_game, game): game for game in games}
        for future in as_completed(future_map):
            game = future_map[future]
            try:
                _, history, bullpen = future.result()
                history_rows.extend(history)
                bullpen_rows.extend(bullpen)
            except Exception as exc:
                failures.append(f"{game.game_id}:{type(exc).__name__}:{exc}")
    if failures:
        raise V7StatsAPIBackfillError("GAME_FEED_COVERAGE_INCOMPLETE:" + "|".join(sorted(failures)[:20]))
    if len(history_rows) != 2 * len(games):
        raise V7StatsAPIBackfillError("SCHEDULE_CHAIN_ROW_COUNT_MISMATCH")

    venue_rows: list[dict[str, Any]] = []
    for venue_id in sorted({g.venue_id for g in games}):
        venue_rows.append(parse_venue(venue_id, fetch_json(venue_url(venue_id))))

    archive_dir = output_root / "archives"
    bullpen_rel = "archives/BULLPEN_USAGE.jsonl"
    history_rel = "archives/MLB_STATSAPI_HISTORY.jsonl"
    venue_rel = "archives/VENUE_REFERENCE.jsonl"
    bullpen_sha = _write_bytes(
        archive_dir / "BULLPEN_USAGE.jsonl",
        _canonical_jsonl(bullpen_rows, lambda r: (r["game_start_time"], r["game_id"], r["team_id"], r["pitcher_id"])),
    )
    history_sha = _write_bytes(
        archive_dir / "MLB_STATSAPI_HISTORY.jsonl",
        _canonical_jsonl(history_rows, lambda r: (r["game_start_time"], r["game_id"], r["team_id"])),
    )
    venue_sha = _write_bytes(
        archive_dir / "VENUE_REFERENCE.jsonl",
        _canonical_jsonl(venue_rows, lambda r: r["venue_id"]),
    )

    _write_manifest(
        root=output_root,
        source_class="BULLPEN_USAGE",
        coverage_start=start_date,
        coverage_end=end_date,
        fields=["game_id", "team_id", "pitcher_id", "pitches", "game_start_time", "final_at"],
        semantics={
            "point_in_time": True,
            "final_before_decision": True,
            "basis": "BACKFILLABLE_PRIOR_FINAL_EVENTS_ONLY",
        },
        evidence_rel=bullpen_rel,
        evidence_sha=bullpen_sha,
        row_count=len(bullpen_rows),
        source_uri=STATSAPI_BASE,
    )
    _write_manifest(
        root=output_root,
        source_class="MLB_STATSAPI_HISTORY",
        coverage_start=start_date,
        coverage_end=end_date,
        fields=["game_id", "team_id", "venue_id", "game_start_time", "status", "final_at"],
        semantics={
            "point_in_time": True,
            "final_before_decision": True,
            "complete_schedule_chain": True,
            "basis": "BACKFILLABLE_PRIOR_FINAL_EVENTS_ONLY",
        },
        evidence_rel=history_rel,
        evidence_sha=history_sha,
        row_count=len(history_rows),
        source_uri=schedule_source,
    )
    _write_manifest(
        root=output_root,
        source_class="VENUE_REFERENCE",
        coverage_start=start_date,
        coverage_end=end_date,
        fields=["venue_id", "latitude", "longitude", "timezone"],
        semantics={"fixed_facts_only": True},
        evidence_rel=venue_rel,
        evidence_sha=venue_sha,
        row_count=len(venue_rows),
        source_uri=f"{STATSAPI_BASE}/api/v1/venues/{{venue_id}}",
    )

    return {
        "state": "ACQUIRED_BACKFILLABLE_SOURCES",
        "coverage_start": start_date,
        "coverage_end": end_date,
        "final_games": len(games),
        "bullpen_rows": len(bullpen_rows),
        "schedule_rows": len(history_rows),
        "venue_rows": len(venue_rows),
        "source_classes": ["BULLPEN_USAGE", "MLB_STATSAPI_HISTORY", "VENUE_REFERENCE"],
        "source_root_note": SOURCE_ROOT_NOTE,
        "promotion_authority": False,
        "model_p_authority": False,
    }
