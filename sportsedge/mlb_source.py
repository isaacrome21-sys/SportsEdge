from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import json
from typing import Any, Callable
from urllib.request import urlopen

BASE = "https://statsapi.mlb.com"


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


def _get_json(url: str, opener: Callable = urlopen) -> dict[str, Any]:
    try:
        with opener(url, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as exc:
        raise MLBSourceError(f"MLB fetch failed: {exc}") from exc


def _pitcher(team: dict[str, Any]) -> tuple[int | None, str | None]:
    p = team.get("probablePitcher") or {}
    return p.get("id"), p.get("fullName")


def parse_schedule(payload: dict[str, Any], retrieved_at: datetime) -> list[GameSnapshot]:
    if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
        raise MLBSourceError("retrieved_at must be timezone-aware")
    out: list[GameSnapshot] = []
    for date_block in payload.get("dates", []):
        for game in date_block.get("games", []):
            teams = game.get("teams") or {}
            away = teams.get("away") or {}
            home = teams.get("home") or {}
            away_team = away.get("team") or {}
            home_team = home.get("team") or {}
            if not all((game.get("gamePk"), away_team.get("id"), home_team.get("id"))):
                raise MLBSourceError("schedule game missing identity")
            apid, apname = _pitcher(away)
            hpid, hpname = _pitcher(home)
            status = ((game.get("status") or {}).get("detailedState") or "UNKNOWN")
            out.append(GameSnapshot(
                int(game["gamePk"]), str(game.get("gameDate", "")), str(status),
                int(away_team["id"]), str(away_team.get("name", "")),
                int(home_team["id"]), str(home_team.get("name", "")),
                apid, apname, hpid, hpname,
                retrieved_at.astimezone(timezone.utc).isoformat(),
            ))
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


def snapshot_to_dict(snapshot: GameSnapshot) -> dict[str, Any]:
    return asdict(snapshot)
