"""Strictly-prior MLB first-five score history for the F5 state candidate.

Only actual inning-level scores from completed games are accepted. Full-game runs
are never scaled or used as a substitute for first-five state. Games missing a
complete innings 1-5 score are skipped rather than imputed.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Mapping
from urllib.parse import urlencode
from urllib.request import urlopen

from .mlb_generic_features import _read_json
from .source_lineage import canonical_json_sha256

F5_FEATURE_VERSION = "mlb_f5_actual_innings_v1"
MIN_HISTORY_GAMES = 10
HISTORY_WINDOW_GAMES = 30
LOOKBACK_DAYS = 240


class MLBF5FeatureError(ValueError):
    pass


def _int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise MLBF5FeatureError(f"{field} must be integer")
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise MLBF5FeatureError(f"{field} must be integer") from exc
    if numeric < 0 or numeric != int(numeric):
        raise MLBF5FeatureError(f"{field} must be nonnegative integer")
    return int(numeric)


def _game_date(game: Mapping[str, Any]) -> date | None:
    raw = game.get("officialDate") or game.get("gameDate")
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _team_id(game: Mapping[str, Any], side: str) -> int | None:
    team = (((game.get("teams") or {}).get(side) or {}).get("team") or {})
    try:
        value = int(team.get("id"))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _first_five_score(game: Mapping[str, Any]) -> tuple[int, int] | None:
    linescore = game.get("linescore")
    if not isinstance(linescore, Mapping):
        return None
    innings = linescore.get("innings")
    if not isinstance(innings, list):
        return None
    by_num: dict[int, Mapping[str, Any]] = {}
    for inning in innings:
        if not isinstance(inning, Mapping):
            continue
        try:
            num = int(inning.get("num"))
        except (TypeError, ValueError):
            continue
        if 1 <= num <= 5:
            by_num[num] = inning
    if set(by_num) != {1, 2, 3, 4, 5}:
        return None
    away = 0
    home = 0
    for num in range(1, 6):
        teams = by_num[num].get("teams")
        if not isinstance(teams, Mapping):
            return None
        away_row = teams.get("away")
        home_row = teams.get("home")
        if not isinstance(away_row, Mapping) or not isinstance(home_row, Mapping):
            return None
        if away_row.get("runs") is None or home_row.get("runs") is None:
            return None
        away += _int(away_row.get("runs"), f"inning_{num}.away_runs")
        home += _int(home_row.get("runs"), f"inning_{num}.home_runs")
    return away, home


class MLBF5HistorySource:
    def __init__(self, *, opener: Callable = urlopen, retrieved_at: datetime | None = None):
        self.opener = opener
        self.retrieved_at = (retrieved_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
        self._cache: dict[tuple[int, date], tuple[dict[str, Any], ...]] = {}

    def team_rows(self, *, team_id: int, target_date: date) -> tuple[dict[str, Any], ...]:
        key = (int(team_id), target_date)
        if key in self._cache:
            return self._cache[key]
        end = target_date - timedelta(days=1)
        start = target_date - timedelta(days=LOOKBACK_DAYS)
        query = urlencode({
            "sportId": 1,
            "teamId": int(team_id),
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "hydrate": "linescore",
        })
        payload = _read_json(f"https://statsapi.mlb.com/api/v1/schedule?{query}", opener=self.opener)
        rows: list[dict[str, Any]] = []
        dates = payload.get("dates")
        if not isinstance(dates, list):
            raise MLBF5FeatureError("MLB_F5_SCHEDULE_DATES_MISSING")
        for day in dates:
            if not isinstance(day, Mapping):
                continue
            games = day.get("games")
            if not isinstance(games, list):
                continue
            for game in games:
                if not isinstance(game, Mapping):
                    continue
                game_date = _game_date(game)
                if game_date is None or game_date >= target_date:
                    continue
                status = game.get("status")
                abstract = str((status or {}).get("abstractGameState") or "") if isinstance(status, Mapping) else ""
                if abstract.lower() != "final":
                    continue
                away_id = _team_id(game, "away")
                home_id = _team_id(game, "home")
                if away_id is None or home_id is None:
                    continue
                if int(team_id) not in {away_id, home_id}:
                    continue
                score = _first_five_score(game)
                if score is None:
                    continue
                away_runs, home_runs = score
                is_away = away_id == int(team_id)
                try:
                    game_pk = int(game.get("gamePk"))
                except (TypeError, ValueError):
                    continue
                rows.append({
                    "game_pk": game_pk,
                    "date": game_date.isoformat(),
                    "team_id": int(team_id),
                    "opponent_id": int(home_id if is_away else away_id),
                    "side": "AWAY" if is_away else "HOME",
                    "runs_for": away_runs if is_away else home_runs,
                    "runs_against": home_runs if is_away else away_runs,
                })
        rows.sort(key=lambda row: (row["date"], row["game_pk"]))
        self._cache[key] = tuple(rows)
        return self._cache[key]

    def matchup_features(self, *, away_team_id: int, home_team_id: int, target_date: date) -> dict[str, Any]:
        away_rows = self.team_rows(team_id=int(away_team_id), target_date=target_date)[-HISTORY_WINDOW_GAMES:]
        home_rows = self.team_rows(team_id=int(home_team_id), target_date=target_date)[-HISTORY_WINDOW_GAMES:]
        if len(away_rows) < MIN_HISTORY_GAMES:
            raise MLBF5FeatureError(f"away F5 history insufficient {len(away_rows)}<{MIN_HISTORY_GAMES}")
        if len(home_rows) < MIN_HISTORY_GAMES:
            raise MLBF5FeatureError(f"home F5 history insufficient {len(home_rows)}<{MIN_HISTORY_GAMES}")
        feature_payload = {
            "away_f5_runs_for": [int(row["runs_for"]) for row in away_rows],
            "away_f5_runs_against": [int(row["runs_against"]) for row in away_rows],
            "home_f5_runs_for": [int(row["runs_for"]) for row in home_rows],
            "home_f5_runs_against": [int(row["runs_against"]) for row in home_rows],
        }
        identity = {
            "feature_version": F5_FEATURE_VERSION,
            "target_date": target_date.isoformat(),
            "away_team_id": int(away_team_id),
            "home_team_id": int(home_team_id),
            "away_rows": list(away_rows),
            "home_rows": list(home_rows),
            "retrieved_at": self.retrieved_at.isoformat(),
        }
        return {
            "feature_version": F5_FEATURE_VERSION,
            "feature_source_hash": canonical_json_sha256(identity),
            "away_history_games": len(away_rows),
            "home_history_games": len(home_rows),
            "features": feature_payload,
        }
