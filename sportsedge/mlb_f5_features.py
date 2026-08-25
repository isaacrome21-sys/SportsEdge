"""Strictly-prior MLB first-five and post-F5 score-path history.

Only actual inning-level scores from completed games are accepted. Full-game runs
are never scaled or used as a substitute for first-five state. Games missing a
complete innings 1-5 score are skipped rather than imputed.

The same official schedule/linescore payload also supports PITCHER_RECORD_WIN's
candidate win-credit state. For each prior team game we derive the minimum number
of starter outs that would have been required to still be pitcher of record when
the team obtained the lead it never relinquished. A non-win has no credit path.
This is score-path state, not a historical pitcher-win-rate proxy.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Mapping
from urllib.parse import urlencode
from urllib.request import urlopen

from .mlb_generic_features import _read_json
from .source_lineage import canonical_json_sha256

F5_FEATURE_VERSION = "mlb_f5_actual_innings_v1"
WIN_CREDIT_PATH_FEATURE_VERSION = "mlb_win_credit_score_path_v1"
MIN_HISTORY_GAMES = 10
HISTORY_WINDOW_GAMES = 30
WIN_CREDIT_HISTORY_WINDOW_GAMES = 60
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


def _final_score(game: Mapping[str, Any]) -> tuple[int, int] | None:
    teams = game.get("teams")
    away_raw = home_raw = None
    if isinstance(teams, Mapping):
        away = teams.get("away")
        home = teams.get("home")
        if isinstance(away, Mapping):
            away_raw = away.get("score")
        if isinstance(home, Mapping):
            home_raw = home.get("score")
    linescore = game.get("linescore")
    if isinstance(linescore, Mapping):
        score_teams = linescore.get("teams")
        if isinstance(score_teams, Mapping):
            away = score_teams.get("away")
            home = score_teams.get("home")
            if away_raw is None and isinstance(away, Mapping):
                away_raw = away.get("runs")
            if home_raw is None and isinstance(home, Mapping):
                home_raw = home.get("runs")
    if away_raw is None or home_raw is None:
        return None
    try:
        return _int(away_raw, "final.away_runs"), _int(home_raw, "final.home_runs")
    except MLBF5FeatureError:
        return None


def _all_inning_runs(game: Mapping[str, Any]) -> tuple[tuple[int, int, int], ...] | None:
    linescore = game.get("linescore")
    innings = linescore.get("innings") if isinstance(linescore, Mapping) else None
    if not isinstance(innings, list):
        return None
    rows: list[tuple[int, int, int]] = []
    for inning in innings:
        if not isinstance(inning, Mapping):
            continue
        try:
            num = int(inning.get("num"))
        except (TypeError, ValueError):
            continue
        teams = inning.get("teams")
        if num < 1 or not isinstance(teams, Mapping):
            continue
        away_row = teams.get("away")
        home_row = teams.get("home")
        if not isinstance(away_row, Mapping) or not isinstance(home_row, Mapping):
            continue
        # A final game's unplayed bottom half can be represented with runs=None.
        # Treat that absent half as zero only after the strict first-five contract
        # has already established that innings 1-5 were fully played.
        away_raw = away_row.get("runs")
        home_raw = home_row.get("runs")
        try:
            away_runs = 0 if away_raw is None else _int(away_raw, f"inning_{num}.away_runs")
            home_runs = 0 if home_raw is None else _int(home_raw, f"inning_{num}.home_runs")
        except MLBF5FeatureError:
            return None
        rows.append((num, away_runs, home_runs))
    rows.sort(key=lambda row: row[0])
    if {row[0] for row in rows if 1 <= row[0] <= 5} != {1, 2, 3, 4, 5}:
        return None
    return tuple(rows)


def _win_credit_required_outs(
    game: Mapping[str, Any], *, team_id: int, away_id: int, home_id: int
) -> int | None:
    """Minimum starter outs needed to own the final permanent lead.

    A nine-inning starter needs 15 outs to qualify for a win. If the selected team
    does not obtain its final, never-relinquished lead until a later offensive half,
    the starter must still be pitcher of record at that point. For an away starter
    a top-N lead can be credited after completing inning N-1; for a home starter a
    bottom-N lead requires completing the top of inning N. Required outs above 27
    are retained and naturally receive zero probability under the current workload
    support rather than being silently capped.
    """
    final_score = _final_score(game)
    inning_rows = _all_inning_runs(game)
    if final_score is None or inning_rows is None:
        return None
    final_away, final_home = final_score
    selected_is_away = int(team_id) == int(away_id)
    if not selected_is_away and int(team_id) != int(home_id):
        raise MLBF5FeatureError("win-credit team identity not in game")
    selected_final = final_away if selected_is_away else final_home
    opponent_final = final_home if selected_is_away else final_away
    if selected_final <= opponent_final:
        return None

    away_total = 0
    home_total = 0
    half_states: list[dict[str, Any]] = []
    for inning, away_runs, home_runs in inning_rows:
        away_total += away_runs
        half_states.append({
            "inning": inning,
            "half": "TOP",
            "away": away_total,
            "home": home_total,
            "selected_offense": selected_is_away,
        })
        home_total += home_runs
        half_states.append({
            "inning": inning,
            "half": "BOTTOM",
            "away": away_total,
            "home": home_total,
            "selected_offense": not selected_is_away,
        })

    # Prefer the official final totals for the terminal identity check; the inning
    # reconstruction is used only to locate when the permanent lead was obtained.
    if away_total != final_away or home_total != final_home:
        return None

    def selected_ahead(state: Mapping[str, Any]) -> bool:
        away = int(state["away"])
        home = int(state["home"])
        return away > home if selected_is_away else home > away

    for index, state in enumerate(half_states):
        if not state["selected_offense"] or not selected_ahead(state):
            continue
        if not all(selected_ahead(later) for later in half_states[index:]):
            continue
        inning = int(state["inning"])
        if selected_is_away:
            raw_required = 3 * max(0, inning - 1)
        else:
            raw_required = 3 * inning
        return max(15, raw_required)
    return None


class MLBF5HistorySource:
    def __init__(self, *, opener: Callable = urlopen, retrieved_at: datetime | None = None):
        self.opener = opener
        self.retrieved_at = (retrieved_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
        self._cache: dict[tuple[int, date], tuple[dict[str, Any], ...]] = {}
        self._payload_cache: dict[tuple[int, date], Mapping[str, Any]] = {}
        self._credit_cache: dict[tuple[int, date], tuple[dict[str, Any], ...]] = {}

    def _schedule_payload(self, *, team_id: int, target_date: date) -> Mapping[str, Any]:
        key = (int(team_id), target_date)
        if key not in self._payload_cache:
            end = target_date - timedelta(days=1)
            start = target_date - timedelta(days=LOOKBACK_DAYS)
            query = urlencode({
                "sportId": 1,
                "teamId": int(team_id),
                "startDate": start.isoformat(),
                "endDate": end.isoformat(),
                "hydrate": "linescore",
            })
            self._payload_cache[key] = _read_json(
                f"https://statsapi.mlb.com/api/v1/schedule?{query}", opener=self.opener
            )
        return self._payload_cache[key]

    @staticmethod
    def _games(payload: Mapping[str, Any]):
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
                if isinstance(game, Mapping):
                    yield game

    def team_rows(self, *, team_id: int, target_date: date) -> tuple[dict[str, Any], ...]:
        key = (int(team_id), target_date)
        if key in self._cache:
            return self._cache[key]
        payload = self._schedule_payload(team_id=int(team_id), target_date=target_date)
        rows: list[dict[str, Any]] = []
        for game in self._games(payload):
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

    def win_credit_rows(self, *, team_id: int, target_date: date) -> tuple[dict[str, Any], ...]:
        """Return strictly-prior team score paths used only by pitcher-win credit."""
        key = (int(team_id), target_date)
        if key in self._credit_cache:
            return self._credit_cache[key]
        payload = self._schedule_payload(team_id=int(team_id), target_date=target_date)
        rows: list[dict[str, Any]] = []
        for game in self._games(payload):
            game_date = _game_date(game)
            if game_date is None or game_date >= target_date:
                continue
            status = game.get("status")
            abstract = str((status or {}).get("abstractGameState") or "") if isinstance(status, Mapping) else ""
            if abstract.lower() != "final":
                continue
            away_id = _team_id(game, "away")
            home_id = _team_id(game, "home")
            if away_id is None or home_id is None or int(team_id) not in {away_id, home_id}:
                continue
            f5_score = _first_five_score(game)
            final_score = _final_score(game)
            if f5_score is None or final_score is None or _all_inning_runs(game) is None:
                continue
            away_f5, home_f5 = f5_score
            is_away = away_id == int(team_id)
            f5_for = away_f5 if is_away else home_f5
            f5_against = home_f5 if is_away else away_f5
            if f5_for > f5_against:
                f5_state = "LEAD"
            elif f5_for < f5_against:
                f5_state = "TRAIL"
            else:
                f5_state = "TIE"
            final_away, final_home = final_score
            final_for = final_away if is_away else final_home
            final_against = final_home if is_away else final_away
            try:
                game_pk = int(game.get("gamePk"))
            except (TypeError, ValueError):
                continue
            required_outs = _win_credit_required_outs(
                game, team_id=int(team_id), away_id=away_id, home_id=home_id
            )
            rows.append({
                "game_pk": game_pk,
                "date": game_date.isoformat(),
                "team_id": int(team_id),
                "opponent_id": int(home_id if is_away else away_id),
                "side": "AWAY" if is_away else "HOME",
                "f5_state": f5_state,
                "f5_runs_for": f5_for,
                "f5_runs_against": f5_against,
                "final_runs_for": final_for,
                "final_runs_against": final_against,
                "team_won": bool(final_for > final_against),
                "win_credit_required_outs": required_outs,
            })
        rows.sort(key=lambda row: (row["date"], row["game_pk"]))
        self._credit_cache[key] = tuple(rows)
        return self._credit_cache[key]

    def win_credit_transition_features(self, *, team_id: int, target_date: date) -> dict[str, Any]:
        rows = self.win_credit_rows(team_id=int(team_id), target_date=target_date)[-WIN_CREDIT_HISTORY_WINDOW_GAMES:]
        if len(rows) < MIN_HISTORY_GAMES:
            raise MLBF5FeatureError(
                f"win-credit history insufficient {len(rows)}<{MIN_HISTORY_GAMES}"
            )
        paths: dict[str, list[int | None]] = {"LEAD": [], "TIE": [], "TRAIL": []}
        for row in rows:
            state = str(row["f5_state"])
            if state not in paths:
                raise MLBF5FeatureError(f"invalid win-credit F5 state:{state}")
            value = row.get("win_credit_required_outs")
            paths[state].append(None if value is None else int(value))
        identity = {
            "feature_version": WIN_CREDIT_PATH_FEATURE_VERSION,
            "target_date": target_date.isoformat(),
            "team_id": int(team_id),
            "rows": list(rows),
            "retrieved_at": self.retrieved_at.isoformat(),
        }
        return {
            "feature_version": WIN_CREDIT_PATH_FEATURE_VERSION,
            "feature_source_hash": canonical_json_sha256(identity),
            "history_games": len(rows),
            "state_counts": {state: len(values) for state, values in paths.items()},
            "paths": paths,
        }

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
