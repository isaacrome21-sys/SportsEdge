"""Compatibility feature coverage for canonical MLB all-market runs.

This module closes feature-construction gaps that remain outside the base
MLBGenericHistorySource catalog: full-game team totals, first-five state,
stateful pitcher-win credit, joint hitter combo markets, and the canonical
either-pitcher markets. All inputs remain strictly prior StatsAPI history; no
sportsbook price is used to create Model_P.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any, Mapping

from .mlb_f5_features import MLBF5HistorySource
from .mlb_generic_features import (
    F5_MARKETS,
    GENERIC_FEATURE_VERSION,
    MLBGenericFeatureError,
    MLBGenericHistorySource,
    _digest,
)
from .pitcher_record_win_engine import build_pitcher_record_win_features

JOINT_HITTER_COMBO_MARKETS = frozenset({
    "HITS_RUNS_STOLEN_BASES",
    "HITS_STOLEN_BASES",
    "HITS_WALKS_STOLEN_BASES",
})
EITHER_PITCHER_MARKETS = frozenset({
    "EITHER_PITCHER_HITS_ALLOWED",
    "EITHER_PITCHER_BB",
    "EITHER_PITCHER_ER",
})
_F5_FEATURE_KEYS = (
    "away_f5_runs_for",
    "away_f5_runs_against",
    "home_f5_runs_for",
    "home_f5_runs_against",
)


def _base(source: MLBGenericHistorySource, *, game_pk: int, market: str, entity_id: str) -> dict[str, Any]:
    return {
        "generic_feature_version": GENERIC_FEATURE_VERSION,
        "game_pk": int(game_pk),
        "market": str(market),
        "entity_id": str(entity_id),
        "retrieved_at": source.retrieved_at.isoformat(),
        "asof": source.retrieved_at.isoformat(),
        "source": "MLB_STATSAPI_CHRONOLOGICAL_GAMELOG",
    }


def _seal(row: dict[str, Any]) -> dict[str, Any]:
    row["source_subset_hash"] = _digest({k: v for k, v in row.items() if k != "source_subset_hash"})
    return row


class _StatsAPIF5ShapeAdapter(MLBF5HistorySource):
    """Normalize the live StatsAPI inning shape without changing any score data.

    Current schedule/linescore responses expose inning ``away`` and ``home`` rows
    directly. The dedicated win-credit reader also accepts its historical nested
    ``teams`` shape. Normalizing the former into the latter keeps the strict-prior
    and minimum-history contracts intact while avoiding a false zero-history read.
    """

    def _schedule_payload(self, *, team_id: int, target_date: date) -> Mapping[str, Any]:
        payload = super()._schedule_payload(team_id=team_id, target_date=target_date)
        dates = payload.get("dates")
        if not isinstance(dates, list):
            return payload
        for day in dates:
            if not isinstance(day, Mapping):
                continue
            games = day.get("games")
            if not isinstance(games, list):
                continue
            for game in games:
                if not isinstance(game, dict):
                    continue
                linescore = game.get("linescore")
                if not isinstance(linescore, dict):
                    continue
                innings = linescore.get("innings")
                if not isinstance(innings, list):
                    continue
                for inning in innings:
                    if not isinstance(inning, dict) or isinstance(inning.get("teams"), Mapping):
                        continue
                    away = inning.get("away")
                    home = inning.get("home")
                    if isinstance(away, Mapping) and isinstance(home, Mapping):
                        inning["teams"] = {"away": dict(away), "home": dict(home)}
        return payload


class MLBAllMarketHistorySource(MLBGenericHistorySource):
    """Feature source with explicit support for every empirical catalog family."""

    def feature_row(
        self,
        *,
        game_pk: int,
        market: str,
        entity_id: str,
        target_date: date,
        away_team_id: int,
        home_team_id: int,
        player_id: int | None = None,
        team_id: int | None = None,
        away_pitcher_id: int | None = None,
        home_pitcher_id: int | None = None,
    ) -> dict[str, Any]:
        if market in JOINT_HITTER_COMBO_MARKETS:
            if player_id is None:
                raise MLBGenericFeatureError("player_id required")
            row = _base(self, game_pk=game_pk, market=market, entity_id=entity_id)
            if team_id is not None:
                row["team_id"] = int(team_id)
            row["features"] = {
                "history_pool": self.hitter_joint_history(player_id=int(player_id), target_date=target_date)
            }
            row["joint_feature_version"] = "mlb_hitter_joint_history_v1"
            return _seal(row)

        if market == "TEAM_TOTALS":
            if team_id is None:
                raise MLBGenericFeatureError("team_id required for TEAM_TOTALS")
            selected = int(team_id)
            if selected not in {int(away_team_id), int(home_team_id)}:
                raise MLBGenericFeatureError("TEAM_TOTALS team_id not in game")
            away_runs, home_runs, _ = self.team_means(
                away_team_id=int(away_team_id),
                home_team_id=int(home_team_id),
                target_date=target_date,
            )
            row = _base(self, game_pk=game_pk, market=market, entity_id=entity_id)
            row["team_id"] = selected
            row["away_mean_runs"] = away_runs
            row["home_mean_runs"] = home_runs
            return _seal(row)

        if market in EITHER_PITCHER_MARKETS:
            if away_pitcher_id is None or home_pitcher_id is None:
                raise MLBGenericFeatureError("both probable pitcher ids required")
            away_pid = int(away_pitcher_id)
            home_pid = int(home_pitcher_id)
            canonical = f"{away_pid}|{home_pid}"
            if str(entity_id) != canonical:
                raise MLBGenericFeatureError("either-pitcher entity_id must be away|home probable pitcher ids")
            row = _base(self, game_pk=game_pk, market=market, entity_id=entity_id)
            row["features"] = {
                "pitcher_a_history": self.pitcher_joint_history(player_id=away_pid, target_date=target_date),
                "pitcher_b_history": self.pitcher_joint_history(player_id=home_pid, target_date=target_date),
            }
            row["joint_feature_version"] = "mlb_pitcher_joint_history_v1"
            return _seal(row)

        if market == "PITCHER_RECORD_WIN":
            if player_id is None:
                raise MLBGenericFeatureError("player_id required for PITCHER_RECORD_WIN")
            if away_pitcher_id is None or home_pitcher_id is None:
                raise MLBGenericFeatureError("both probable pitcher ids required for PITCHER_RECORD_WIN")
            game = SimpleNamespace(
                game_pk=int(game_pk),
                away_team_id=int(away_team_id),
                home_team_id=int(home_team_id),
                away_probable_pitcher_id=int(away_pitcher_id),
                home_probable_pitcher_id=int(home_pitcher_id),
            )
            f5_source = _StatsAPIF5ShapeAdapter(
                opener=self.opener,
                retrieved_at=self.retrieved_at,
            )
            payload = build_pitcher_record_win_features(
                self,
                game=game,
                pitcher_id=int(player_id),
                target_date=target_date,
                f5_source=f5_source,
            )
            row = _base(self, game_pk=game_pk, market=market, entity_id=entity_id)
            row["team_id"] = int(payload["team_id"])
            row["team_side"] = str(payload["team_side"])
            row["features"] = dict(payload)
            row["joint_feature_version"] = str(payload["feature_version"])
            return _seal(row)

        row = super().feature_row(
            game_pk=game_pk,
            market=market,
            entity_id=entity_id,
            target_date=target_date,
            away_team_id=away_team_id,
            home_team_id=home_team_id,
            player_id=player_id,
            team_id=team_id,
        )
        if market in F5_MARKETS:
            missing = [key for key in _F5_FEATURE_KEYS if key not in row]
            if missing:
                raise MLBGenericFeatureError(f"F5 state features missing: {missing}")
            row["features"] = {key: list(row[key]) for key in _F5_FEATURE_KEYS}
            row["joint_feature_version"] = "mlb_f5_strict_prior_linescore_v1"
            return _seal(row)
        return row