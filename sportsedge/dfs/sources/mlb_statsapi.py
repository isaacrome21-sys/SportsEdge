from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
from typing import Any, Callable, Iterable
from urllib.parse import urlencode

from ..types import DKPlayer
from .common import normalize_name, normalize_team, public_json
from .types import DfsContextEvidence

BASE = "https://statsapi.mlb.com/api/v1"
LIVE_BASE = "https://statsapi.mlb.com/api/v1.1"


class MLBStatsApiContextClient:
    """MLB StatsAPI adapter for current schedule, probable pitchers and posted lineups."""

    def __init__(self, getter: Callable[[str], dict[str, Any]] | None = None) -> None:
        self._getter = getter or public_json

    def schedule(self, slate_date: date) -> dict[str, Any]:
        query = urlencode({"sportId": 1, "date": slate_date.isoformat(), "hydrate": "probablePitcher,team,venue"})
        return self._getter(f"{BASE}/schedule?{query}")

    def game_feed(self, game_pk: int) -> dict[str, Any]:
        return self._getter(f"{LIVE_BASE}/game/{int(game_pk)}/feed/live")

    @staticmethod
    def _team_abbr(team: dict[str, Any]) -> str:
        return normalize_team(team.get("abbreviation") or team.get("teamCode") or team.get("fileCode") or "")

    @staticmethod
    def _lineup(team_box: dict[str, Any]) -> list[dict[str, Any]]:
        players = team_box.get("players") if isinstance(team_box.get("players"), dict) else {}
        out: list[dict[str, Any]] = []
        for item in players.values():
            if not isinstance(item, dict):
                continue
            order = item.get("battingOrder")
            if order in (None, "", 0, "0"):
                continue
            try:
                order_i = int(order) // 100 if int(order) >= 100 else int(order)
            except (TypeError, ValueError):
                continue
            if order_i < 1 or order_i > 9:
                continue
            person = item.get("person") if isinstance(item.get("person"), dict) else {}
            name = str(person.get("fullName") or person.get("name") or "").strip()
            if not name:
                continue
            out.append({"order": order_i, "name": name, "mlb_id": str(person.get("id") or "")})
        out.sort(key=lambda x: (x["order"], x["name"]))
        return out

    def build_context(self, slate_date: date) -> DfsContextEvidence:
        schedule = self.schedule(slate_date)
        games: list[dict[str, Any]] = []
        for date_row in schedule.get("dates") or []:
            if not isinstance(date_row, dict):
                continue
            for scheduled in date_row.get("games") or []:
                if not isinstance(scheduled, dict) or scheduled.get("gamePk") is None:
                    continue
                game_pk = int(scheduled["gamePk"])
                feed = self.game_feed(game_pk)
                game_data = feed.get("gameData") if isinstance(feed.get("gameData"), dict) else {}
                live_data = feed.get("liveData") if isinstance(feed.get("liveData"), dict) else {}
                teams = game_data.get("teams") if isinstance(game_data.get("teams"), dict) else {}
                boxscore = live_data.get("boxscore") if isinstance(live_data.get("boxscore"), dict) else {}
                box_teams = boxscore.get("teams") if isinstance(boxscore.get("teams"), dict) else {}
                home_obj = teams.get("home") if isinstance(teams.get("home"), dict) else {}
                away_obj = teams.get("away") if isinstance(teams.get("away"), dict) else {}
                home = self._team_abbr(home_obj)
                away = self._team_abbr(away_obj)
                probable = game_data.get("probablePitchers") if isinstance(game_data.get("probablePitchers"), dict) else {}
                status = game_data.get("status") if isinstance(game_data.get("status"), dict) else {}
                weather = game_data.get("weather") if isinstance(game_data.get("weather"), dict) else {}
                venue = game_data.get("venue") if isinstance(game_data.get("venue"), dict) else {}
                datetime_obj = game_data.get("datetime") if isinstance(game_data.get("datetime"), dict) else {}
                games.append(
                    {
                        "game_pk": game_pk,
                        "home": home,
                        "away": away,
                        "start_time": datetime_obj.get("dateTime") or scheduled.get("gameDate") or "",
                        "status": {
                            "abstract": status.get("abstractGameState") or "",
                            "detailed": status.get("detailedState") or "",
                            "coded": status.get("codedGameState") or "",
                        },
                        "venue": {"id": venue.get("id"), "name": venue.get("name") or ""},
                        "weather": {
                            "condition": weather.get("condition") or "",
                            "temp_f": weather.get("temp"),
                            "wind": weather.get("wind") or "",
                        },
                        "probable_pitchers": {
                            side: {
                                "name": str((probable.get(side) or {}).get("fullName") or ""),
                                "mlb_id": str((probable.get(side) or {}).get("id") or ""),
                            }
                            for side in ("home", "away")
                            if isinstance(probable.get(side), dict)
                        },
                        "lineups": {
                            "home": self._lineup(box_teams.get("home") if isinstance(box_teams.get("home"), dict) else {}),
                            "away": self._lineup(box_teams.get("away") if isinstance(box_teams.get("away"), dict) else {}),
                        },
                    }
                )
        now = datetime.now(timezone.utc)
        return DfsContextEvidence(
            sport="MLB",
            source="MLB_STATSAPI",
            retrieved_at=now,
            games=tuple(games),
            metadata={"slate_date": slate_date.isoformat()},
        )

    @staticmethod
    def apply_to_players(
        players: Iterable[DKPlayer],
        evidence: DfsContextEvidence,
    ) -> tuple[list[DKPlayer], dict[str, Any]]:
        """Apply only high-certainty lineup/probable/postponement information.

        A posted nine-man lineup is enforced only when all nine starters can be
        reconciled to the DK team pool. This prevents spelling/ID mismatches from
        silently deleting a real starter.
        """
        out = list(players)
        index_by_team: dict[str, list[int]] = {}
        for idx, player in enumerate(out):
            index_by_team.setdefault(normalize_team(player.team), []).append(idx)

        confirmed_teams: list[str] = []
        probable_teams: list[str] = []
        postponed_teams: list[str] = []
        reconciliation_blocks: list[str] = []
        for game in evidence.games:
            home = normalize_team(str(game.get("home") or ""))
            away = normalize_team(str(game.get("away") or ""))
            status = game.get("status") if isinstance(game.get("status"), dict) else {}
            status_text = f"{status.get('abstract', '')} {status.get('detailed', '')}".casefold()
            if "postpon" in status_text or "cancel" in status_text:
                for team in (home, away):
                    if team and team in index_by_team:
                        postponed_teams.append(team)
                        for idx in index_by_team[team]:
                            out[idx] = replace(out[idx], is_disabled=True, status="MLB_POSTPONED")
                continue

            lineups = game.get("lineups") if isinstance(game.get("lineups"), dict) else {}
            probable = game.get("probable_pitchers") if isinstance(game.get("probable_pitchers"), dict) else {}
            for side, team in (("home", home), ("away", away)):
                if not team or team not in index_by_team:
                    continue
                team_indices = index_by_team[team]
                dk_hitters = [i for i in team_indices if not out[i].is_pitcher]
                posted = lineups.get(side) if isinstance(lineups.get(side), list) else []
                starter_names = {normalize_name(str(x.get("name") or "")) for x in posted if isinstance(x, dict)}
                starter_names.discard("")
                if len(starter_names) == 9:
                    matched = {normalize_name(out[i].name) for i in dk_hitters if normalize_name(out[i].name) in starter_names}
                    if len(matched) == 9:
                        confirmed_teams.append(team)
                        for idx in dk_hitters:
                            if normalize_name(out[idx].name) not in starter_names:
                                out[idx] = replace(out[idx], is_disabled=True, status="MLB_NOT_IN_CONFIRMED_LINEUP")
                    else:
                        reconciliation_blocks.append(f"{team}:LINEUP_MATCH_{len(matched)}_OF_9")

                pinfo = probable.get(side) if isinstance(probable.get(side), dict) else {}
                pname = normalize_name(str(pinfo.get("name") or ""))
                if pname:
                    pitcher_indices = [i for i in team_indices if out[i].is_pitcher]
                    matched_pitchers = [i for i in pitcher_indices if normalize_name(out[i].name) == pname]
                    if len(matched_pitchers) == 1:
                        probable_teams.append(team)
                        keep = matched_pitchers[0]
                        for idx in pitcher_indices:
                            if idx != keep:
                                out[idx] = replace(out[idx], is_disabled=True, status="MLB_NOT_PROBABLE_STARTER")
                    elif pitcher_indices:
                        reconciliation_blocks.append(f"{team}:PROBABLE_PITCHER_MATCH_{len(matched_pitchers)}")

        diagnostics = {
            "mlb_context_source": evidence.source,
            "mlb_context_retrieved_at": evidence.retrieved_at.isoformat(),
            "mlb_context_game_count": len(evidence.games),
            "confirmed_lineup_teams": sorted(set(confirmed_teams)),
            "probable_pitcher_teams": sorted(set(probable_teams)),
            "postponed_teams": sorted(set(postponed_teams)),
            "reconciliation_blocks": sorted(set(reconciliation_blocks)),
        }
        return out, diagnostics
