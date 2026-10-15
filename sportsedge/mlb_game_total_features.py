"""Strictly-prior MLB full-game final-score history for Total Runs 3-Way.

The FULL_GAME counterpart of sportsedge.mlb_period_features, in its own
module so the F5/period feature files are not modified (the F5 feature
file's exact bytes are pinned in the checked-in code-defined model
surface, config/mlb_model_surface_v1.json). Only actual final scores
from completed games are accepted, read through the F5 source's own
verified reduction (mlb_f5_features._final_score: the schedule
payload's team scores, falling back to the linescore team totals).
Period scores are never scaled up to a full game, and games without a
verified final score are skipped rather than imputed.
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
    _final_score,
    _game_date,
    _team_id,
)
from .source_lineage import canonical_json_sha256

GAME_TOTAL_FEATURE_VERSION = "mlb_game_total_actual_finals_v1"


class MLBGameTotalHistorySource(MLBF5HistorySource):
    """Strictly-prior full-game final-score history from the same
    official schedule payloads the F5/period sources read; only the
    score reduction differs (the verified final score)."""

    def __init__(self, *, opener: Callable = urlopen, retrieved_at: datetime | None = None):
        super().__init__(opener=opener, retrieved_at=retrieved_at)
        self._game_cache: dict[tuple[int, date], tuple[dict[str, Any], ...]] = {}
        self._game_league_cache: dict[date, dict[str, Any]] = {}

    def game_team_rows(self, *, team_id: int, target_date: date
                       ) -> tuple[dict[str, Any], ...]:
        key = (int(team_id), target_date)
        if key in self._game_cache:
            return self._game_cache[key]
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
            score = _final_score(game)
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
        self._game_cache[key] = tuple(rows)
        return self._game_cache[key]

    def game_league_prior(self, *, target_date: date) -> dict[str, Any]:
        """Strictly-prior league full-game team-runs PMF (all completed
        regular-season team-halves in the prior 370 days, target date
        excluded) -- the F5/period league prior's recipe at the
        full-game score scale."""
        if target_date in self._game_league_cache:
            return dict(self._game_league_cache[target_date])
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
            score = _final_score(game)
            if score is None:
                continue
            try:
                game_pk = int(game.get("gamePk"))
            except (TypeError, ValueError):
                continue
            away_runs, home_runs = score
            for value in (away_runs, home_runs):
                counts[int(value)] = counts.get(int(value), 0) + 1
            halves += 2
            rows.append({
                "game_pk": game_pk,
                "date": game_date.isoformat(),
                "away_runs": int(away_runs),
                "home_runs": int(home_runs),
            })
        if halves < MIN_LEAGUE_HALVES:
            raise MLBF5FeatureError(
                f"league game prior insufficient {halves}<{MIN_LEAGUE_HALVES}"
            )
        prior = {
            "league_game_pmf": {
                str(k): float(count) / float(halves)
                for k, count in sorted(counts.items())
            },
            "league_prior_halves": int(halves),
            "league_prior_strength": LEAGUE_PRIOR_STRENGTH,
            "league_prior_source_hash": canonical_json_sha256({
                "feature_version": GAME_TOTAL_FEATURE_VERSION,
                "target_date": target_date.isoformat(),
                "lookback_days": LEAGUE_LOOKBACK_DAYS,
                "game_type": "R",
                "rows": rows,
            }),
        }
        self._game_league_cache[target_date] = dict(prior)
        return dict(prior)

    def game_matchup_features(self, *, away_team_id: int, home_team_id: int,
                              target_date: date) -> dict[str, Any]:
        away_rows = self.game_team_rows(
            team_id=int(away_team_id), target_date=target_date)[-HISTORY_WINDOW_GAMES:]
        home_rows = self.game_team_rows(
            team_id=int(home_team_id), target_date=target_date)[-HISTORY_WINDOW_GAMES:]
        if len(away_rows) < MIN_HISTORY_GAMES:
            raise MLBF5FeatureError(f"away game history insufficient {len(away_rows)}<{MIN_HISTORY_GAMES}")
        if len(home_rows) < MIN_HISTORY_GAMES:
            raise MLBF5FeatureError(f"home game history insufficient {len(home_rows)}<{MIN_HISTORY_GAMES}")
        league_prior = self.game_league_prior(target_date=target_date)
        feature_payload = {
            "away_game_runs_for": [int(row["runs_for"]) for row in away_rows],
            "away_game_runs_against": [int(row["runs_against"]) for row in away_rows],
            "home_game_runs_for": [int(row["runs_for"]) for row in home_rows],
            "home_game_runs_against": [int(row["runs_against"]) for row in home_rows],
            "league_game_pmf": dict(league_prior["league_game_pmf"]),
            "league_prior_halves": int(league_prior["league_prior_halves"]),
            "league_prior_strength": int(league_prior["league_prior_strength"]),
        }
        identity = {
            "feature_version": GAME_TOTAL_FEATURE_VERSION,
            "target_date": target_date.isoformat(),
            "away_team_id": int(away_team_id),
            "home_team_id": int(home_team_id),
            "away_rows": list(away_rows),
            "home_rows": list(home_rows),
            "league_prior_source_hash": league_prior["league_prior_source_hash"],
            "retrieved_at": self.retrieved_at.isoformat(),
        }
        return {
            "feature_version": GAME_TOTAL_FEATURE_VERSION,
            "feature_source_hash": canonical_json_sha256(identity),
            "away_history_games": len(away_rows),
            "home_history_games": len(home_rows),
            "league_prior_source_hash": league_prior["league_prior_source_hash"],
            "features": feature_payload,
        }
