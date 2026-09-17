"""Chronological native feature builder for expanded MLB shadow markets."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from math import exp, isfinite
from statistics import fmean
from typing import Any, Callable, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen

GENERIC_FEATURE_VERSION = "mlb_generic_feature_v2"
PLAYER_COUNT_MARKETS = frozenset({
    "HOME_RUNS", "RBI", "RUNS", "HITS_RUNS_RBIS", "SINGLES", "DOUBLES", "TRIPLES",
    "BATTER_BB", "BATTER_K", "STOLEN_BASES", "PITCHER_K", "PITCHER_HITS_ALLOWED",
    "PITCHER_BB", "PITCHER_ER", "PITCHER_OUTS",
})
PA_BOUNDED_BATTER_MARKETS = frozenset({"BATTER_K", "BATTER_BB", "SINGLES", "DOUBLES"})
BINARY_MARKETS = frozenset({"PITCHER_RECORD_WIN", "FIRST_HOME_RUN"})
GAME_MARKETS = frozenset({"MONEYLINE", "RUN_LINE", "TOTALS", "NRFI", "YRFI", "F5_MONEYLINE", "F5_RUN_LINE", "F5_TOTALS", "F5_TEAM_TOTALS"})
F5_MARKETS = frozenset({"F5_MONEYLINE", "F5_RUN_LINE", "F5_TOTALS", "F5_TEAM_TOTALS"})

BATTER_STAT_KEYS = {
    "HOME_RUNS": "homeRuns", "RBI": "rbi", "RUNS": "runs", "DOUBLES": "doubles",
    "TRIPLES": "triples", "BATTER_BB": "baseOnBalls", "BATTER_K": "strikeOuts",
    "STOLEN_BASES": "stolenBases",
}
PITCHER_STAT_KEYS = {
    "PITCHER_K": "strikeOuts", "PITCHER_HITS_ALLOWED": "hits",
    "PITCHER_BB": "baseOnBalls", "PITCHER_ER": "earnedRuns",
}

class MLBGenericFeatureError(ValueError):
    pass

def _digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()

def _read_json(url: str, *, opener: Callable) -> Mapping[str, Any]:
    req = Request(url, headers={"Accept": "application/json", "User-Agent": "SportsEdge/1.0"})
    try:
        with opener(req, timeout=15) as response:
            value = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise MLBGenericFeatureError(f"MLB_GENERIC_HISTORY_FETCH_FAILED: {url}") from exc
    if not isinstance(value, Mapping):
        raise MLBGenericFeatureError("MLB_GENERIC_HISTORY_NOT_OBJECT")
    return value

def _number(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise MLBGenericFeatureError(f"{field}: boolean is invalid")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise MLBGenericFeatureError(f"{field}: nonnumeric") from exc
    if not isfinite(out):
        raise MLBGenericFeatureError(f"{field}: nonfinite")
    return out

def _nonnegative_integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not isfinite(numeric) or numeric < 0 or numeric != int(numeric):
        return None
    return int(numeric)

def _outs_from_ip(value: Any) -> float:
    text = str(value).strip()
    if not text:
        raise MLBGenericFeatureError("inningsPitched missing")
    if "." not in text:
        return float(int(text) * 3)
    whole, frac = text.split(".", 1)
    if frac not in {"0", "1", "2"}:
        raise MLBGenericFeatureError("inningsPitched uses invalid baseball notation")
    return float(int(whole) * 3 + int(frac))

def _split_date(split: Mapping[str, Any]) -> date | None:
    raw = split.get("date")
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None

def _splits(payload: Mapping[str, Any], *, target_date: date) -> list[Mapping[str, Any]]:
    rows: list[Mapping[str, Any]] = []
    stats = payload.get("stats")
    if not isinstance(stats, list):
        return rows
    for block in stats:
        if not isinstance(block, Mapping):
            continue
        for split in block.get("splits") or []:
            if not isinstance(split, Mapping):
                continue
            d = _split_date(split)
            if d is None or d >= target_date:
                continue
            stat = split.get("stat")
            if isinstance(stat, Mapping):
                rows.append({"date": d, "stat": stat})
    rows.sort(key=lambda x: x["date"])
    return rows

def _schedule_games(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    games: list[Mapping[str, Any]] = []
    dates = payload.get("dates")
    if not isinstance(dates, list):
        return games
    for day in dates:
        if not isinstance(day, Mapping):
            continue
        for game in day.get("games") or []:
            if isinstance(game, Mapping):
                games.append(game)
    games.sort(key=lambda game: (str(game.get("gameDate") or game.get("officialDate") or ""), str(game.get("gamePk") or "")))
    return games

def _first_five_score(game: Mapping[str, Any]) -> tuple[int, int] | None:
    """Return (away, home) runs through five complete innings or None.

    The schedule endpoint's hydrated linescore exposes inning objects with separate
    away/home run counts. Requiring all innings 1..5 prevents final-score scaling,
    partial-game leakage, and silent substitution when a linescore is incomplete.
    """
    status = game.get("status")
    if isinstance(status, Mapping) and str(status.get("abstractGameState") or "").lower() != "final":
        return None
    linescore = game.get("linescore")
    if not isinstance(linescore, Mapping):
        return None
    innings = linescore.get("innings")
    if not isinstance(innings, list):
        return None
    first_five: dict[int, tuple[int, int]] = {}
    for inning in innings:
        if not isinstance(inning, Mapping):
            continue
        number = _nonnegative_integer(inning.get("num"))
        if number is None or number < 1 or number > 5 or number in first_five:
            continue
        away = inning.get("away")
        home = inning.get("home")
        if not isinstance(away, Mapping) or not isinstance(home, Mapping):
            return None
        away_runs = _nonnegative_integer(away.get("runs"))
        home_runs = _nonnegative_integer(home.get("runs"))
        if away_runs is None or home_runs is None:
            return None
        first_five[number] = (away_runs, home_runs)
    if set(first_five) != {1, 2, 3, 4, 5}:
        return None
    return (
        sum(first_five[inning][0] for inning in range(1, 6)),
        sum(first_five[inning][1] for inning in range(1, 6)),
    )

class MLBGenericHistorySource:
    def __init__(self, *, opener: Callable = urlopen, retrieved_at: datetime | None = None):
        self.opener = opener
        self.retrieved_at = (retrieved_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
        self._player_cache: dict[tuple[int, str, int], Mapping[str, Any]] = {}
        self._team_cache: dict[tuple[int, int], Mapping[str, Any]] = {}
        self._f5_cache: dict[tuple[int, date], tuple[tuple[int, int], ...]] = {}

    def _player_season(self, player_id: int, group: str, season: int) -> Mapping[str, Any]:
        key = (int(player_id), group, int(season))
        if key not in self._player_cache:
            query = urlencode({"stats": "gameLog", "group": group, "season": season, "gameType": "R"})
            self._player_cache[key] = _read_json(f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?{query}", opener=self.opener)
        return self._player_cache[key]

    def _team_season(self, team_id: int, season: int) -> Mapping[str, Any]:
        key = (int(team_id), int(season))
        if key not in self._team_cache:
            query = urlencode({"stats": "gameLog", "group": "hitting", "season": season, "gameType": "R"})
            self._team_cache[key] = _read_json(f"https://statsapi.mlb.com/api/v1/teams/{team_id}/stats?{query}", opener=self.opener)
        return self._team_cache[key]

    def _team_f5_history(self, *, team_id: int, target_date: date) -> tuple[tuple[int, int], ...]:
        key = (int(team_id), target_date)
        if key not in self._f5_cache:
            end_date = target_date - timedelta(days=1)
            start_date = target_date - timedelta(days=370)
            query = urlencode({
                "sportId": 1,
                "teamId": int(team_id),
                "gameType": "R",
                "startDate": start_date.isoformat(),
                "endDate": end_date.isoformat(),
                "hydrate": "linescore",
            })
            payload = _read_json(f"https://statsapi.mlb.com/api/v1/schedule?{query}", opener=self.opener)
            rows: list[tuple[int, int]] = []
            for game in _schedule_games(payload):
                official_date = game.get("officialDate")
                if official_date:
                    try:
                        if date.fromisoformat(str(official_date)[:10]) >= target_date:
                            continue
                    except ValueError:
                        continue
                score = _first_five_score(game)
                if score is None:
                    continue
                teams = game.get("teams")
                if not isinstance(teams, Mapping):
                    continue
                away = teams.get("away")
                home = teams.get("home")
                if not isinstance(away, Mapping) or not isinstance(home, Mapping):
                    continue
                away_team = away.get("team")
                home_team = home.get("team")
                if not isinstance(away_team, Mapping) or not isinstance(home_team, Mapping):
                    continue
                away_id = _nonnegative_integer(away_team.get("id"))
                home_id = _nonnegative_integer(home_team.get("id"))
                if int(team_id) == away_id:
                    rows.append((score[0], score[1]))
                elif int(team_id) == home_id:
                    rows.append((score[1], score[0]))
            self._f5_cache[key] = tuple(rows[-30:])
        return self._f5_cache[key]

    def player_rows(self, *, player_id: int, group: str, target_date: date) -> list[Mapping[str, Any]]:
        rows: list[Mapping[str, Any]] = []
        for season in (target_date.year - 1, target_date.year):
            rows.extend(_splits(self._player_season(player_id, group, season), target_date=target_date))
        rows.sort(key=lambda x: x["date"])
        return rows

    def team_rows(self, *, team_id: int, target_date: date) -> list[Mapping[str, Any]]:
        rows: list[Mapping[str, Any]] = []
        for season in (target_date.year - 1, target_date.year):
            rows.extend(_splits(self._team_season(team_id, season), target_date=target_date))
        rows.sort(key=lambda x: x["date"])
        return rows

    @staticmethod
    def _mean(values: list[float], *, minimum: int, window: int, name: str) -> float:
        usable = values[-window:]
        if len(usable) < minimum:
            raise MLBGenericFeatureError(f"{name}: insufficient chronological sample {len(usable)}<{minimum}")
        return float(fmean(usable))

    @staticmethod
    def _batter_value(stat: Mapping[str, Any], market: str) -> float:
        if market == "HITS_RUNS_RBIS":
            return _number(stat.get("hits", 0), "hits") + _number(stat.get("runs", 0), "runs") + _number(stat.get("rbi", 0), "rbi")
        if market == "SINGLES":
            value = _number(stat.get("hits", 0), "hits") - _number(stat.get("doubles", 0), "doubles") - _number(stat.get("triples", 0), "triples") - _number(stat.get("homeRuns", 0), "homeRuns")
            return max(0.0, value)
        key = BATTER_STAT_KEYS.get(market)
        if key is None:
            raise MLBGenericFeatureError(f"unsupported batter market {market}")
        return _number(stat.get(key, 0), key)

    def batter_expected(self, *, player_id: int, market: str, target_date: date) -> float:
        rows = self.player_rows(player_id=player_id, group="hitting", target_date=target_date)
        values = [self._batter_value(row["stat"], market) for row in rows]
        return self._mean(values, minimum=10, window=30, name=f"batter:{market}")

    def batter_expected_and_pa(self, *, player_id: int, market: str, target_date: date) -> tuple[float, float]:
        rows = self.player_rows(player_id=player_id, group="hitting", target_date=target_date)[-30:]
        if len(rows) < 10:
            raise MLBGenericFeatureError(f"batter:{market}: insufficient chronological sample {len(rows)}<10")
        counts: list[float] = []
        pas: list[float] = []
        for row in rows:
            stat = row["stat"]
            counts.append(self._batter_value(stat, market))
            if "plateAppearances" not in stat:
                raise MLBGenericFeatureError("plateAppearances missing from bounded-count PIT row")
            pas.append(_number(stat.get("plateAppearances"), "plateAppearances"))
        return float(fmean(counts)), float(fmean(pas))

    def pitcher_expected(self, *, player_id: int, market: str, target_date: date) -> float:
        rows = self.player_rows(player_id=player_id, group="pitching", target_date=target_date)
        starts = [r for r in rows if _number(r["stat"].get("gamesStarted", 0), "gamesStarted") >= 1]
        values: list[float] = []
        for row in starts:
            s = row["stat"]
            if market == "PITCHER_OUTS":
                value = _outs_from_ip(s.get("inningsPitched"))
            else:
                key = PITCHER_STAT_KEYS.get(market)
                if key is None:
                    raise MLBGenericFeatureError(f"unsupported pitcher market {market}")
                value = _number(s.get(key, 0), key)
            values.append(value)
        return self._mean(values, minimum=5, window=10, name=f"pitcher:{market}")

    def pitcher_win_probability(self, *, player_id: int, target_date: date) -> float:
        rows = self.player_rows(player_id=player_id, group="pitching", target_date=target_date)
        starts = [r for r in rows if _number(r["stat"].get("gamesStarted", 0), "gamesStarted") >= 1]
        values = [1.0 if _number(r["stat"].get("wins", 0), "wins") >= 1 else 0.0 for r in starts]
        return min(1.0, max(0.0, self._mean(values, minimum=5, window=20, name="pitcher:win")))

    def team_means(self, *, away_team_id: int, home_team_id: int, target_date: date) -> tuple[float, float, float]:
        def one(team_id: int) -> tuple[float, float]:
            rows = self.team_rows(team_id=team_id, target_date=target_date)
            runs = [_number(r["stat"].get("runs", 0), "runs") for r in rows]
            hrs = [_number(r["stat"].get("homeRuns", 0), "homeRuns") for r in rows]
            return self._mean(runs, minimum=10, window=30, name=f"team:{team_id}:runs"), self._mean(hrs, minimum=10, window=30, name=f"team:{team_id}:hr")
        away_runs, away_hr = one(away_team_id)
        home_runs, home_hr = one(home_team_id)
        return away_runs, home_runs, max(0.0, away_hr + home_hr)

    def feature_row(self, *, game_pk: int, market: str, entity_id: str, target_date: date, away_team_id: int, home_team_id: int, player_id: int | None = None, team_id: int | None = None) -> dict[str, Any]:
        base: dict[str, Any] = {
            "generic_feature_version": GENERIC_FEATURE_VERSION, "game_pk": int(game_pk),
            "market": str(market), "entity_id": str(entity_id),
            "retrieved_at": self.retrieved_at.isoformat(), "asof": self.retrieved_at.isoformat(),
            "source": "MLB_STATSAPI_CHRONOLOGICAL_GAMELOG",
        }
        if team_id is not None:
            base["team_id"] = int(team_id)

        if market in PLAYER_COUNT_MARKETS:
            if player_id is None:
                raise MLBGenericFeatureError("player_id required")
            if market.startswith("PITCHER_"):
                base["expected_count"] = self.pitcher_expected(player_id=player_id, market=market, target_date=target_date)
            elif market in PA_BOUNDED_BATTER_MARKETS:
                expected, projected_pa = self.batter_expected_and_pa(player_id=player_id, market=market, target_date=target_date)
                base["expected_count"] = expected
                base["projected_pa"] = projected_pa
            else:
                base["expected_count"] = self.batter_expected(player_id=player_id, market=market, target_date=target_date)
        elif market == "PITCHER_RECORD_WIN":
            if player_id is None:
                raise MLBGenericFeatureError("player_id required")
            base["event_probability"] = self.pitcher_win_probability(player_id=player_id, target_date=target_date)
        elif market == "FIRST_HOME_RUN":
            if player_id is None:
                raise MLBGenericFeatureError("player_id required")
            player_hr = self.batter_expected(player_id=player_id, market="HOME_RUNS", target_date=target_date)
            _, _, game_hr = self.team_means(away_team_id=away_team_id, home_team_id=home_team_id, target_date=target_date)
            base["event_probability"] = 0.0 if game_hr <= 0 else min(1.0, max(0.0, (player_hr / game_hr) * (1.0 - exp(-game_hr))))
        elif market in GAME_MARKETS:
            if market in F5_MARKETS:
                away_history = self._team_f5_history(team_id=away_team_id, target_date=target_date)
                home_history = self._team_f5_history(team_id=home_team_id, target_date=target_date)
                base["away_f5_runs_for"] = [row[0] for row in away_history]
                base["away_f5_runs_against"] = [row[1] for row in away_history]
                base["home_f5_runs_for"] = [row[0] for row in home_history]
                base["home_f5_runs_against"] = [row[1] for row in home_history]
                base["source"] = "MLB_STATSAPI_STRICT_PRIOR_F5_LINESCORE"
            else:
                away_runs, home_runs, _ = self.team_means(away_team_id=away_team_id, home_team_id=home_team_id, target_date=target_date)
                base["away_mean_runs"] = away_runs
                base["home_mean_runs"] = home_runs
        else:
            raise MLBGenericFeatureError(f"unsupported generic market {market}")

        base["source_subset_hash"] = _digest({k: v for k, v in base.items() if k != "source_subset_hash"})
        return base