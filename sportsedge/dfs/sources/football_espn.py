from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
from typing import Any, Callable, Iterable
from urllib.parse import urlencode

from ..types import DKPlayer
from .common import normalize_name, normalize_team, public_json
from .types import DfsContextEvidence, PlayerAvailability

BASE = "https://site.api.espn.com/apis/site/v2/sports/football"


class EspnFootballContextClient:
    """No-key ESPN public-facing football context adapter for NFL and CFB."""

    LEAGUE = {"NFL": "nfl", "CFB": "college-football"}

    def __init__(self, getter: Callable[[str], dict[str, Any]] | None = None) -> None:
        self._getter = getter or public_json

    def scoreboard(self, sport: str, slate_date: date) -> dict[str, Any]:
        league = self.LEAGUE[sport.upper()]
        query = urlencode({"dates": slate_date.strftime("%Y%m%d"), "limit": 200})
        return self._getter(f"{BASE}/{league}/scoreboard?{query}")

    def summary(self, sport: str, event_id: str) -> dict[str, Any]:
        league = self.LEAGUE[sport.upper()]
        return self._getter(f"{BASE}/{league}/summary?event={event_id}")

    @staticmethod
    def _competition(event: dict[str, Any]) -> dict[str, Any]:
        comps = event.get("competitions") if isinstance(event.get("competitions"), list) else []
        return comps[0] if comps and isinstance(comps[0], dict) else {}

    @staticmethod
    def _team_map(competition: dict[str, Any]) -> dict[str, str]:
        out: dict[str, str] = {}
        competitors = competition.get("competitors") if isinstance(competition.get("competitors"), list) else []
        for comp in competitors:
            if not isinstance(comp, dict):
                continue
            team = comp.get("team") if isinstance(comp.get("team"), dict) else {}
            abbr = normalize_team(str(team.get("abbreviation") or ""))
            side = str(comp.get("homeAway") or "").lower()
            if abbr and side in {"home", "away"}:
                out[side] = abbr
        return out

    @staticmethod
    def _extract_injuries(summary: dict[str, Any], team_id_to_abbr: dict[str, str], retrieved_at: datetime) -> list[PlayerAvailability]:
        root = summary.get("injuries")
        groups = root if isinstance(root, list) else []
        out: list[PlayerAvailability] = []
        for group in groups:
            if not isinstance(group, dict):
                continue
            group_team = group.get("team") if isinstance(group.get("team"), dict) else {}
            group_team_id = str(group_team.get("id") or "")
            group_abbr = normalize_team(str(group_team.get("abbreviation") or team_id_to_abbr.get(group_team_id, "")))
            rows = group.get("injuries") if isinstance(group.get("injuries"), list) else None
            if rows is None:
                rows = [group]
            for item in rows:
                if not isinstance(item, dict):
                    continue
                athlete = item.get("athlete") if isinstance(item.get("athlete"), dict) else {}
                name = str(athlete.get("displayName") or athlete.get("fullName") or item.get("name") or "").strip()
                if not name:
                    continue
                item_team = item.get("team") if isinstance(item.get("team"), dict) else {}
                team_id = str(item_team.get("id") or athlete.get("teamId") or group_team_id or "")
                team = normalize_team(str(item_team.get("abbreviation") or group_abbr or team_id_to_abbr.get(team_id, "")))
                status_obj = item.get("status")
                if isinstance(status_obj, dict):
                    status = str(status_obj.get("name") or status_obj.get("type") or status_obj.get("description") or "")
                else:
                    status = str(status_obj or item.get("type") or "")
                detail_obj = item.get("details")
                if isinstance(detail_obj, dict):
                    detail = " ".join(str(detail_obj.get(k) or "") for k in ("type", "detail", "returnDate", "fantasyStatus")).strip()
                else:
                    detail = str(detail_obj or item.get("description") or "")
                out.append(
                    PlayerAvailability(
                        name=name,
                        team=team,
                        status=status,
                        detail=detail,
                        source="ESPN_PUBLIC_FOOTBALL",
                        updated_at=retrieved_at,
                        player_id=str(athlete.get("id") or ""),
                    )
                )
        return out

    def build_context(self, sport: str, slate_date: date) -> DfsContextEvidence:
        sport = sport.upper()
        if sport not in self.LEAGUE:
            raise ValueError(f"DFS_ESPN_UNSUPPORTED_SPORT:{sport}")
        scoreboard = self.scoreboard(sport, slate_date)
        retrieved_at = datetime.now(timezone.utc)
        games: list[dict[str, Any]] = []
        availability: list[PlayerAvailability] = []
        for event in scoreboard.get("events") or []:
            if not isinstance(event, dict):
                continue
            event_id = str(event.get("id") or "")
            if not event_id:
                continue
            competition = self._competition(event)
            teams = self._team_map(competition)
            status_obj = competition.get("status") if isinstance(competition.get("status"), dict) else {}
            status_type = status_obj.get("type") if isinstance(status_obj.get("type"), dict) else {}
            venue = competition.get("venue") if isinstance(competition.get("venue"), dict) else {}
            weather = competition.get("weather") if isinstance(competition.get("weather"), dict) else {}
            summary: dict[str, Any]
            try:
                summary = self.summary(sport, event_id)
            except Exception:
                summary = {}
            team_id_to_abbr: dict[str, str] = {}
            for comp in competition.get("competitors") or []:
                if not isinstance(comp, dict):
                    continue
                team_obj = comp.get("team") if isinstance(comp.get("team"), dict) else {}
                team_id = str(team_obj.get("id") or "")
                abbr = normalize_team(str(team_obj.get("abbreviation") or ""))
                if team_id and abbr:
                    team_id_to_abbr[team_id] = abbr
            availability.extend(self._extract_injuries(summary, team_id_to_abbr, retrieved_at))
            games.append(
                {
                    "event_id": event_id,
                    "home": teams.get("home", ""),
                    "away": teams.get("away", ""),
                    "start_time": event.get("date") or competition.get("date") or "",
                    "status": {
                        "name": status_type.get("name") or "",
                        "description": status_type.get("description") or status_obj.get("displayClock") or "",
                        "completed": bool(status_type.get("completed", False)),
                    },
                    "venue": {"name": venue.get("fullName") or venue.get("name") or ""},
                    "weather": weather,
                    "summary_available": bool(summary),
                }
            )
        return DfsContextEvidence(
            sport=sport,
            source="ESPN_PUBLIC_FOOTBALL",
            retrieved_at=retrieved_at,
            games=tuple(games),
            availability=tuple(availability),
            metadata={"slate_date": slate_date.isoformat()},
        )

    @staticmethod
    def apply_to_players(
        players: Iterable[DKPlayer],
        evidence: DfsContextEvidence,
    ) -> tuple[list[DKPlayer], dict[str, Any]]:
        out = list(players)
        hard_unavailable: dict[tuple[str, str], PlayerAvailability] = {}
        for item in evidence.availability:
            if item.unavailable and item.team:
                hard_unavailable[(normalize_team(item.team), normalize_name(item.name))] = item

        disabled_injuries: list[str] = []
        disabled_games: list[str] = []
        for idx, player in enumerate(out):
            key = (normalize_team(player.team), normalize_name(player.name))
            item = hard_unavailable.get(key)
            if item is not None:
                out[idx] = replace(out[idx], is_disabled=True, status=f"PUBLIC_INJURY:{item.status or item.detail}")
                disabled_injuries.append(f"{player.team}:{player.name}")

        for game in evidence.games:
            status = game.get("status") if isinstance(game.get("status"), dict) else {}
            status_text = f"{status.get('name', '')} {status.get('description', '')}".casefold()
            if "postpon" not in status_text and "cancel" not in status_text:
                continue
            teams = {normalize_team(str(game.get("home") or "")), normalize_team(str(game.get("away") or ""))}
            teams.discard("")
            for idx, player in enumerate(out):
                if normalize_team(player.team) in teams:
                    out[idx] = replace(out[idx], is_disabled=True, status="PUBLIC_GAME_POSTPONED")
                    disabled_games.append(player.team)

        diagnostics = {
            "football_context_source": evidence.source,
            "football_context_retrieved_at": evidence.retrieved_at.isoformat(),
            "football_context_game_count": len(evidence.games),
            "public_availability_count": len(evidence.availability),
            "hard_unavailable_players": sorted(set(disabled_injuries)),
            "postponed_teams": sorted(set(disabled_games)),
            "missing_injury_rows_are_unknown": True,
        }
        return out, diagnostics
