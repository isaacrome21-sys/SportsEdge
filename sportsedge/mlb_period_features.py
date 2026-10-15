"""Strictly-prior MLB first-3 / first-7 innings score-path history.

The period counterpart of sportsedge.mlb_f5_features, in its own
module so the F5 feature file -- whose exact bytes are pinned in the
checked-in code-defined model surface (config/mlb_model_surface_v1.json)
-- is not modified. Only actual inning-level scores from completed
games are accepted. Full-game runs are never scaled or used as a
substitute for period state. Games missing a complete innings 1..N
score (N = 3 or 7) are skipped rather than imputed.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Callable, Mapping
from urllib.request import urlopen

from .mlb_f5_features import (
    HISTORY_WINDOW_GAMES,
    LEAGUE_LOOKBACK_DAYS,
    LEAGUE_PRIOR_STRENGTH,
    MIN_HISTORY_GAMES,
    MIN_LEAGUE_HALVES,
    MLBF5FeatureError,
    MLBF5HistorySource,
    _game_date,
    _inning_teams,
    _int,
    _team_id,
)
from .source_lineage import canonical_json_sha256

PERIOD_FEATURE_VERSION = "mlb_period_actual_innings_v1"
PERIOD_INNINGS = (3, 7)


def _period_score(game: Mapping[str, Any], innings: int) -> tuple[int, int] | None:
    """Actual cumulative runs through ``innings`` completed innings.

    The F3/F7 generalization of mlb_f5_features._first_five_score:
    every inning 1..innings must be present with recorded runs for
    BOTH teams; anything missing skips the game rather than imputing.
    """
    if innings < 1:
        return None
    linescore = game.get("linescore")
    if not isinstance(linescore, Mapping):
        return None
    inning_rows = linescore.get("innings")
    if not isinstance(inning_rows, list):
        return None
    by_num: dict[int, Mapping[str, Any]] = {}
    for inning in inning_rows:
        if not isinstance(inning, Mapping):
            continue
        try:
            num = int(inning.get("num"))
        except (TypeError, ValueError):
            continue
        if 1 <= num <= innings:
            by_num[num] = inning
    if set(by_num) != set(range(1, innings + 1)):
        return None
    away = 0
    home = 0
    for num in range(1, innings + 1):
        teams = _inning_teams(by_num[num])
        if teams is None:
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


class MLBPeriodHistorySource(MLBF5HistorySource):
    """Strictly-prior first-3 / first-7 history from the same payloads.

    Reuses MLBF5HistorySource's official schedule/linescore reads; only
    the score reduction differs (cumulative runs through inning 3 or 7
    via _period_score). Games missing a complete innings 1..N score are
    skipped rather than imputed, exactly as the F5 source skips games
    missing a complete innings 1-5 score.
    """

    def __init__(self, *, opener: Callable = urlopen, retrieved_at: datetime | None = None):
        super().__init__(opener=opener, retrieved_at=retrieved_at)
        self._period_cache: dict[tuple[int, int, date], tuple[dict[str, Any], ...]] = {}
        self._period_league_cache: dict[tuple[int, date], dict[str, Any]] = {}

    @staticmethod
    def _check_innings(innings: int) -> int:
        if innings not in PERIOD_INNINGS:
            raise MLBF5FeatureError(f"unsupported period innings: {innings}")
        return innings

    def period_team_rows(self, *, team_id: int, target_date: date,
                         innings: int) -> tuple[dict[str, Any], ...]:
        innings = self._check_innings(innings)
        key = (innings, int(team_id), target_date)
        if key in self._period_cache:
            return self._period_cache[key]
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
            score = _period_score(game, innings)
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
        self._period_cache[key] = tuple(rows)
        return self._period_cache[key]

    def period_league_prior(self, *, target_date: date, innings: int) -> dict[str, Any]:
        """Strictly-prior league period PMF (all completed regular-season
        team-halves in the prior 370 days, target date excluded) -- the
        F5 league prior's recipe at the period's own score scale."""
        innings = self._check_innings(innings)
        key = (innings, target_date)
        if key in self._period_league_cache:
            return dict(self._period_league_cache[key])
        payload = self._league_schedule_payload(target_date=target_date)
        counts: dict[int, int] = {}
        halves = 0
        rows: list[dict[str, Any]] = []
        for game in self._games(payload):
            game_date = _game_date(game)
            if game_date is None or game_date >= target_date:
                continue
            status = game.get("status")
            abstract = str((status or {}).get("abstractGameState") or "") if isinstance(status, Mapping) else ""
            if abstract.lower() != "final":
                continue
            score = _period_score(game, innings)
            if score is None:
                continue
            try:
                game_pk = int(game.get("gamePk"))
            except (TypeError, ValueError):
                continue
            away_period, home_period = score
            for value in (away_period, home_period):
                counts[int(value)] = counts.get(int(value), 0) + 1
            halves += 2
            rows.append({
                "game_pk": game_pk,
                "date": game_date.isoformat(),
                "away_period": int(away_period),
                "home_period": int(home_period),
            })
        if halves < MIN_LEAGUE_HALVES:
            raise MLBF5FeatureError(
                f"league period prior insufficient {halves}<{MIN_LEAGUE_HALVES}"
            )
        prior = {
            "league_period_pmf": {
                str(k): float(count) / float(halves)
                for k, count in sorted(counts.items())
            },
            "league_prior_halves": int(halves),
            "league_prior_strength": LEAGUE_PRIOR_STRENGTH,
            "league_prior_source_hash": canonical_json_sha256({
                "feature_version": f"{PERIOD_FEATURE_VERSION}_f{innings}",
                "target_date": target_date.isoformat(),
                "lookback_days": LEAGUE_LOOKBACK_DAYS,
                "game_type": "R",
                "innings": innings,
                "rows": rows,
            }),
        }
        self._period_league_cache[key] = dict(prior)
        return dict(prior)

    def period_matchup_features(self, *, away_team_id: int, home_team_id: int,
                                target_date: date, innings: int) -> dict[str, Any]:
        innings = self._check_innings(innings)
        away_rows = self.period_team_rows(
            team_id=int(away_team_id), target_date=target_date,
            innings=innings)[-HISTORY_WINDOW_GAMES:]
        home_rows = self.period_team_rows(
            team_id=int(home_team_id), target_date=target_date,
            innings=innings)[-HISTORY_WINDOW_GAMES:]
        if len(away_rows) < MIN_HISTORY_GAMES:
            raise MLBF5FeatureError(f"away period history insufficient {len(away_rows)}<{MIN_HISTORY_GAMES}")
        if len(home_rows) < MIN_HISTORY_GAMES:
            raise MLBF5FeatureError(f"home period history insufficient {len(home_rows)}<{MIN_HISTORY_GAMES}")
        league_prior = self.period_league_prior(target_date=target_date, innings=innings)
        feature_payload = {
            "away_period_runs_for": [int(row["runs_for"]) for row in away_rows],
            "away_period_runs_against": [int(row["runs_against"]) for row in away_rows],
            "home_period_runs_for": [int(row["runs_for"]) for row in home_rows],
            "home_period_runs_against": [int(row["runs_against"]) for row in home_rows],
            "league_period_pmf": dict(league_prior["league_period_pmf"]),
            "league_prior_halves": int(league_prior["league_prior_halves"]),
            "league_prior_strength": int(league_prior["league_prior_strength"]),
        }
        identity = {
            "feature_version": f"{PERIOD_FEATURE_VERSION}_f{innings}",
            "target_date": target_date.isoformat(),
            "away_team_id": int(away_team_id),
            "home_team_id": int(home_team_id),
            "away_rows": list(away_rows),
            "home_rows": list(home_rows),
            "league_prior_source_hash": league_prior["league_prior_source_hash"],
            "retrieved_at": self.retrieved_at.isoformat(),
        }
        return {
            "feature_version": f"{PERIOD_FEATURE_VERSION}_f{innings}",
            "feature_source_hash": canonical_json_sha256(identity),
            "away_history_games": len(away_rows),
            "home_history_games": len(home_rows),
            "league_prior_source_hash": league_prior["league_prior_source_hash"],
            "features": feature_payload,
        }
