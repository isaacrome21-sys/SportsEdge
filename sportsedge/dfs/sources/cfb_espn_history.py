from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urlencode

from .common import normalize_team, public_json
from ..types import DKPlayer

BASE = "https://site.api.espn.com/apis/site/v2/sports/football/college-football"
MODEL_SOURCE = "ESPN_PUBLIC_CFB_COMPLETED_GAME_SUMMARIES"


def _canonical_sha(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return sha256(raw).hexdigest()


def _dt(value: Any) -> datetime | None:
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        return None
    try:
        out = datetime.fromisoformat(text)
    except ValueError:
        return None
    if out.tzinfo is None:
        out = out.replace(tzinfo=timezone.utc)
    return out.astimezone(timezone.utc)


def _norm_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())


def _find_key(keys: list[Any], *hints: str) -> int | None:
    normalized = [_norm_key(k) for k in keys]
    for hint in hints:
        needle = _norm_key(hint)
        for i, key in enumerate(normalized):
            if needle and needle in key:
                return i
    return None


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _combined(value: Any) -> tuple[float, float | None]:
    text = str(value or "").strip()
    for delim in ("/", "-"):
        if delim in text:
            left, right = text.split(delim, 1)
            try:
                return float(left), float(right)
            except ValueError:
                return 0.0, None
    return _number(value), None


def _group_value(keys: list[Any], stats: list[Any], *hints: str) -> float:
    idx = _find_key(keys, *hints)
    if idx is None or idx >= len(stats):
        return 0.0
    value, _ = _combined(stats[idx])
    return value


def _catch_prior(position: str) -> float:
    pos = position.upper()
    if pos == "RB":
        return .74
    if pos == "TE":
        return .68
    return .63


def parse_espn_cfb_summary(
    payload: Mapping[str, Any],
    *,
    event_id: str,
    season: int,
    week: int,
) -> list[dict[str, Any]]:
    """Normalize one completed ESPN CFB box score by stat-key names, never index."""
    boxscore = payload.get("boxscore") if isinstance(payload.get("boxscore"), Mapping) else {}
    teams = boxscore.get("players") if isinstance(boxscore.get("players"), list) else []
    by_player: dict[tuple[str, str], dict[str, Any]] = {}
    for team_block in teams:
        if not isinstance(team_block, Mapping):
            continue
        team_obj = team_block.get("team") if isinstance(team_block.get("team"), Mapping) else {}
        team = normalize_team(str(team_obj.get("abbreviation") or team_obj.get("shortDisplayName") or ""))
        if not team:
            continue
        groups = team_block.get("statistics") if isinstance(team_block.get("statistics"), list) else []
        for group in groups:
            if not isinstance(group, Mapping):
                continue
            category = str(group.get("name") or "").casefold()
            if category not in {"passing", "rushing", "receiving"}:
                continue
            keys = list(group.get("keys") or [])
            athletes = group.get("athletes") if isinstance(group.get("athletes"), list) else []
            for athlete_row in athletes:
                if not isinstance(athlete_row, Mapping):
                    continue
                athlete = athlete_row.get("athlete") if isinstance(athlete_row.get("athlete"), Mapping) else {}
                athlete_id = str(athlete.get("id") or "").strip()
                name = str(athlete.get("displayName") or athlete.get("fullName") or "").strip()
                if not athlete_id or not name:
                    continue
                position_obj = athlete.get("position") if isinstance(athlete.get("position"), Mapping) else {}
                position = str(position_obj.get("abbreviation") or "").upper()
                raw_stats = list(athlete_row.get("stats") or [])
                row = by_player.setdefault((team, athlete_id), {
                    "player_id": f"ESPN:{athlete_id}",
                    "player_display_name": name,
                    "player_name": name,
                    "position": position,
                    "team": team,
                    "opponent_team": "",
                    "season": int(season),
                    "week": int(week),
                    "season_type": "REG",
                    "game_id": str(event_id),
                    "attempts": 0.0,
                    "passing_yards": 0.0,
                    "passing_tds": 0.0,
                    "interceptions": 0.0,
                    "carries": 0.0,
                    "rushing_yards": 0.0,
                    "rushing_tds": 0.0,
                    "targets": 0.0,
                    "receptions": 0.0,
                    "receiving_yards": 0.0,
                    "receiving_tds": 0.0,
                    "fumbles_lost": 0.0,
                    "targets_estimated": False,
                })
                if category == "passing":
                    comp_idx = _find_key(keys, "completion")
                    if comp_idx is not None and comp_idx < len(raw_stats):
                        _, attempts = _combined(raw_stats[comp_idx])
                        if attempts is not None:
                            row["attempts"] = attempts
                    row["passing_yards"] = _group_value(keys, raw_stats, "passingyards")
                    row["passing_tds"] = _group_value(keys, raw_stats, "passingtouchdown")
                    row["interceptions"] = _group_value(keys, raw_stats, "interception")
                elif category == "rushing":
                    row["carries"] = _group_value(keys, raw_stats, "rushingattempt")
                    row["rushing_yards"] = _group_value(keys, raw_stats, "rushingyards")
                    row["rushing_tds"] = _group_value(keys, raw_stats, "rushingtouchdown")
                elif category == "receiving":
                    row["receptions"] = _group_value(keys, raw_stats, "reception")
                    row["receiving_yards"] = _group_value(keys, raw_stats, "receivingyards")
                    row["receiving_tds"] = _group_value(keys, raw_stats, "receivingtouchdown")
                    row["targets"] = _group_value(keys, raw_stats, "target")

    team_names = sorted({team for team, _ in by_player})
    if len(team_names) == 2:
        for row in by_player.values():
            row["opponent_team"] = team_names[1] if row["team"] == team_names[0] else team_names[0]
    for row in by_player.values():
        if row["targets"] <= 0 and row["receptions"] > 0:
            prior = _catch_prior(str(row.get("position") or ""))
            row["targets"] = max(row["receptions"], round(row["receptions"] / prior))
            row["targets_estimated"] = True
    return list(by_player.values())


class EspnCFBHistoryClient:
    def __init__(self, getter: Callable[[str], dict[str, Any]] | None = None) -> None:
        self._getter = getter or public_json

    def teams(self) -> dict[str, tuple[str, str]]:
        payload = self._getter(f"{BASE}/teams?limit=500")
        out: dict[str, tuple[str, str]] = {}
        sports = payload.get("sports") if isinstance(payload.get("sports"), list) else []
        for sport in sports:
            leagues = sport.get("leagues") if isinstance(sport, Mapping) and isinstance(sport.get("leagues"), list) else []
            for league in leagues:
                team_rows = league.get("teams") if isinstance(league, Mapping) and isinstance(league.get("teams"), list) else []
                for wrapper in team_rows:
                    team = wrapper.get("team") if isinstance(wrapper, Mapping) and isinstance(wrapper.get("team"), Mapping) else {}
                    abbr = normalize_team(str(team.get("abbreviation") or ""))
                    team_id = str(team.get("id") or "")
                    name = str(team.get("displayName") or team.get("location") or "")
                    if abbr and team_id:
                        out[abbr] = (team_id, name)
        if not out:
            raise ValueError("CFB_ESPN_TEAM_INDEX_EMPTY")
        return out

    def schedule(self, team_id: str, season: int) -> dict[str, Any]:
        query = urlencode({"season": int(season)})
        return self._getter(f"{BASE}/teams/{team_id}/schedule?{query}")

    def summary(self, event_id: str) -> dict[str, Any]:
        return self._getter(f"{BASE}/summary?event={event_id}")

    def build_history(
        self,
        *,
        players: Iterable[DKPlayer],
        slate_start: datetime,
        max_games: int = 6,
        include_prior_season: bool = True,
        workers: int = 8,
    ) -> dict[str, Any]:
        if slate_start.tzinfo is None or slate_start.utcoffset() is None:
            raise ValueError("CFB_ESPN_SLATE_TIMEZONE_REQUIRED")
        lock = slate_start.astimezone(timezone.utc)
        pool = [p for p in players if not p.is_disabled]
        teams = sorted({normalize_team(p.team) for p in pool if p.team})
        team_index = self.teams()
        missing = sorted(team for team in teams if team not in team_index)
        if missing:
            raise ValueError("CFB_ESPN_TEAM_ID_MISSING:" + ",".join(missing))
        season = lock.year
        seasons = (season, season - 1) if include_prior_season else (season,)

        schedule_payloads: dict[tuple[str, int], dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=max(1, min(workers, 12))) as pool_exec:
            futures = {
                pool_exec.submit(self.schedule, team_index[team][0], yr): (team, yr)
                for team in teams for yr in seasons
            }
            for future in as_completed(futures):
                key = futures[future]
                schedule_payloads[key] = future.result()

        events: dict[str, dict[str, Any]] = {}
        for (team, yr), payload in schedule_payloads.items():
            candidates: list[dict[str, Any]] = []
            for event in payload.get("events") or []:
                if not isinstance(event, Mapping):
                    continue
                event_id = str(event.get("id") or "")
                stamp = _dt(event.get("date"))
                status = event.get("status") if isinstance(event.get("status"), Mapping) else {}
                status_type = status.get("type") if isinstance(status.get("type"), Mapping) else {}
                if not event_id or stamp is None or stamp >= lock or not bool(status_type.get("completed", False)):
                    continue
                week_obj = event.get("week") if isinstance(event.get("week"), Mapping) else {}
                candidates.append({
                    "event_id": event_id,
                    "date": stamp,
                    "season": yr,
                    "week": int(week_obj.get("number") or 0),
                })
            candidates.sort(key=lambda row: row["date"])
            for event in candidates[-int(max_games):]:
                prior = events.get(event["event_id"])
                if prior is None or event["date"] > prior["date"]:
                    events[event["event_id"]] = event

        if not events:
            raise ValueError("CFB_ESPN_COMPLETED_HISTORY_EMPTY")
        summaries: dict[str, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=max(1, min(workers, 12))) as pool_exec:
            futures = {pool_exec.submit(self.summary, event_id): event_id for event_id in events}
            for future in as_completed(futures):
                summaries[futures[future]] = future.result()

        rows: list[dict[str, Any]] = []
        source_hashes: dict[str, str] = {}
        for event_id, meta in events.items():
            payload = summaries[event_id]
            source_hashes[event_id] = _canonical_sha(payload)
            rows.extend(parse_espn_cfb_summary(
                payload,
                event_id=event_id,
                season=int(meta["season"]),
                week=int(meta["week"]),
            ))

        grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            if normalize_team(str(row.get("team") or "")) not in teams:
                continue
            grouped[(normalize_team(str(row["team"])), str(row["player_id"]))].append(row)
        history_players: list[dict[str, Any]] = []
        for (team, player_id), games in sorted(grouped.items()):
            games.sort(key=lambda row: (int(row["season"]), int(row["week"]), str(row["game_id"])))
            window = games[-int(max_games):]
            history_players.append({
                "player_id": player_id,
                "team": team,
                "player_display_name": window[-1]["player_display_name"],
                "position": window[-1]["position"],
                "games": window,
            })
        if not history_players:
            raise ValueError("CFB_ESPN_PLAYER_HISTORY_EMPTY")
        manifest = {
            "team_index_sha256": _canonical_sha(team_index),
            "schedule_sha256": {
                f"{team}:{yr}": _canonical_sha(payload)
                for (team, yr), payload in sorted(schedule_payloads.items())
            },
            "summary_sha256": dict(sorted(source_hashes.items())),
        }
        return {
            "schema_version": 1,
            "sport": "CFB",
            "season": season,
            "teams": teams,
            "source": MODEL_SOURCE,
            "source_manifest_sha256": _canonical_sha(manifest),
            "provenance_mode": "CANONICAL_RESPONSE_HASH_LIVE_PIT_NOT_ARCHIVAL_REPLAY",
            "max_games": int(max_games),
            "player_count": len(history_players),
            "targets_estimated_rows": sum(1 for row in rows if row.get("targets_estimated")),
            "players": history_players,
        }
