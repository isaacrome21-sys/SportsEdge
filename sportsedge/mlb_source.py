from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import json
from typing import Any, Callable
from urllib.request import urlopen
from zoneinfo import ZoneInfo

from .source_lineage import canonical_game_identity

BASE = "https://statsapi.mlb.com"
SAVANT_PREVIEW_BASE = "https://baseballsavant.mlb.com/preview"
CHICAGO_TZ = ZoneInfo("America/Chicago")


class MLBSourceError(RuntimeError):
    pass


@dataclass(frozen=True)
class GameSnapshot:
    game_pk: int
    game_date: str
    status: str
    away_id: int
    away_name: str
    home_id: int
    home_name: str
    away_probable_pitcher_id: int | None
    away_probable_pitcher_name: str | None
    home_probable_pitcher_id: int | None
    home_probable_pitcher_name: str | None
    retrieved_at: str
    source: str = "MLB_STATSAPI_SCHEDULE"
    game_number: int | None = None
    double_header: str | None = None
    venue_id: int | None = None
    official_date: str | None = None
    detailed_status: str | None = None


def _get_json(url: str, opener: Callable = urlopen) -> dict[str, Any]:
    try:
        with opener(url, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as exc:
        raise MLBSourceError(f"MLB fetch failed: {exc}") from exc


def _pitcher(team: dict[str, Any]) -> tuple[int | None, str | None]:
    p = team.get("probablePitcher") or {}
    return p.get("id"), p.get("fullName")


def parse_game_start(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise MLBSourceError("schedule game missing gameDate")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise MLBSourceError(f"invalid MLB gameDate: {value}") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise MLBSourceError("MLB gameDate must be timezone-aware")
    return dt.astimezone(timezone.utc)


def game_time_chicago(value: str | GameSnapshot) -> str:
    raw = value.game_date if isinstance(value, GameSnapshot) else value
    return parse_game_start(raw).astimezone(CHICAGO_TZ).isoformat()


def savant_preview_url(snapshot: GameSnapshot) -> str:
    """Return the canonical Baseball Savant Statcast Game Preview URL for a game."""
    if snapshot.official_date:
        try:
            game_day = datetime.fromisoformat(snapshot.official_date).date()
        except ValueError as exc:
            raise MLBSourceError(f"invalid MLB officialDate: {snapshot.official_date}") from exc
    else:
        game_day = parse_game_start(snapshot.game_date).astimezone(CHICAGO_TZ).date()
    return (
        f"{SAVANT_PREVIEW_BASE}?game_pk={snapshot.game_pk}"
        f"&game_date={game_day.strftime('%m/%d/%Y')}"
    )


def _optional_positive_int(name: str, value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise MLBSourceError(f"{name} must be a positive integer")
    try:
        out = int(value)
    except (TypeError, ValueError) as exc:
        raise MLBSourceError(f"{name} must be a positive integer") from exc
    if out <= 0:
        raise MLBSourceError(f"{name} must be a positive integer")
    return out


def parse_schedule(payload: dict[str, Any], retrieved_at: datetime) -> list[GameSnapshot]:
    if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
        raise MLBSourceError("retrieved_at must be timezone-aware")
    out: list[GameSnapshot] = []
    seen_game_pks: set[int] = set()
    for date_block in payload.get("dates", []):
        for game in date_block.get("games", []):
            teams = game.get("teams") or {}
            away = teams.get("away") or {}
            home = teams.get("home") or {}
            away_team = away.get("team") or {}
            home_team = home.get("team") or {}
            if not all((game.get("gamePk"), away_team.get("id"), home_team.get("id"))):
                raise MLBSourceError("schedule game missing identity")
            game_pk = int(game["gamePk"])
            if game_pk in seen_game_pks:
                raise MLBSourceError(f"duplicate gamePk in schedule: {game_pk}")
            seen_game_pks.add(game_pk)
            game_start = parse_game_start(game.get("gameDate"))
            apid, apname = _pitcher(away)
            hpid, hpname = _pitcher(home)
            status_obj = game.get("status") or {}
            abstract_status = status_obj.get("abstractGameState")
            if abstract_status not in {"Preview", "Live", "Final"}:
                raise MLBSourceError("GAME_STATE_MISSING_OR_INVALID")
            detailed_status = status_obj.get("detailedState")
            if detailed_status is not None:
                detailed_status = str(detailed_status)
            game_number = _optional_positive_int("gameNumber", game.get("gameNumber"))
            double_header = game.get("doubleHeader")
            if double_header is not None:
                double_header = str(double_header)
                if double_header not in {"Y", "N", "S"}:
                    raise MLBSourceError("doubleHeader must be Y, N, S, or null")
            if double_header in {"Y", "S"} and game_number is None:
                raise MLBSourceError("doubleheader game missing gameNumber")
            venue_id = _optional_positive_int("venue.id", (game.get("venue") or {}).get("id"))
            official_date = game.get("officialDate") or date_block.get("date")
            if official_date is not None:
                official_date = str(official_date)
            out.append(GameSnapshot(
                game_pk, game_start.isoformat(), str(abstract_status),
                int(away_team["id"]), str(away_team.get("name", "")),
                int(home_team["id"]), str(home_team.get("name", "")),
                apid, apname, hpid, hpname,
                retrieved_at.astimezone(timezone.utc).isoformat(),
                game_number=game_number, double_header=double_header,
                venue_id=venue_id, official_date=official_date,
                detailed_status=detailed_status,
            ))
    out.sort(key=lambda g: (parse_game_start(g.game_date), g.game_pk))
    return out


def fetch_schedule(date_iso: str, opener: Callable = urlopen, now: datetime | None = None) -> list[GameSnapshot]:
    now = now or datetime.now(timezone.utc)
    url = f"{BASE}/api/v1/schedule?sportId=1&date={date_iso}&hydrate=probablePitcher,team"
    return parse_schedule(_get_json(url, opener), now)


def parse_confirmed_lineup(boxscore: dict[str, Any], side: str) -> list[dict[str, Any]]:
    if side not in ("home", "away"):
        raise MLBSourceError("side must be home or away")
    team = ((boxscore.get("teams") or {}).get(side) or {})
    players = team.get("players") or {}
    lineup: list[dict[str, Any]] = []
    for player in players.values():
        order = player.get("battingOrder")
        person = player.get("person") or {}
        if order is None or int(order) <= 0:
            continue
        code = int(order)
        slot, sequence = divmod(code, 100)
        lineup.append({
            "player_id": person.get("id"),
            "name": person.get("fullName"),
            "batting_order_code": code,
            "slot": slot,
            "sequence": sequence,
            "substitution_evidence": sequence > 0,
        })
    lineup.sort(key=lambda x: (x["slot"], x["sequence"], x["player_id"] or 0))
    return lineup


def fetch_boxscore(game_pk: int, opener: Callable = urlopen) -> dict[str, Any]:
    return _get_json(f"{BASE}/api/v1/game/{int(game_pk)}/boxscore", opener)


def game_identity(snapshot: GameSnapshot):
    return canonical_game_identity(
        mlb_game_pk=snapshot.game_pk,
        scheduled_start=snapshot.game_date,
        away_team_id=snapshot.away_id,
        home_team_id=snapshot.home_id,
        game_number=snapshot.game_number,
    )


def snapshot_to_dict(snapshot: GameSnapshot) -> dict[str, Any]:
    out = asdict(snapshot)
    identity = game_identity(snapshot)
    out["game_time_utc"] = parse_game_start(snapshot.game_date).isoformat()
    out["game_time_ct"] = game_time_chicago(snapshot)
    out["sportsedge_game_id"] = identity.sportsedge_game_id
    out["mlb_game_pk"] = identity.mlb_game_pk
    out["savant_preview_url"] = savant_preview_url(snapshot)
    return out
