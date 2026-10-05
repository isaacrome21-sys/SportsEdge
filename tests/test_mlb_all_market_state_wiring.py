from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from sportsedge.generic_card_pipeline import _model_input
from sportsedge.generic_market_engine import generic_market_engine_adapter
from sportsedge.mlb_all_market_features import (
    MLBAllMarketHistorySource,
    _StatsAPIF5ShapeAdapter,
)
from sportsedge.mlb_f5_features import MLBF5HistorySource
from sportsedge.mlb_generic_features import MLBGenericHistorySource


class TestMLBAllMarketStateWiring(unittest.TestCase):
    def _source(self) -> MLBAllMarketHistorySource:
        return MLBAllMarketHistorySource(
            opener=lambda *args, **kwargs: None,
            retrieved_at=datetime(2026, 9, 29, 21, 52, tzinfo=timezone.utc),
        )

    def test_statsapi_adapter_adds_legacy_teams_wrapper(self):
        payload = {
            "dates": [
                {
                    "games": [
                        {
                            "linescore": {
                                "innings": [
                                    {"num": 1, "away": {"runs": 1}, "home": {"runs": 0}},
                                    {"num": 2, "away": {"runs": 0}, "home": {"runs": 1}},
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        source = _StatsAPIF5ShapeAdapter(
            opener=lambda *args, **kwargs: None,
            retrieved_at=datetime(2026, 9, 29, tzinfo=timezone.utc),
        )
        with patch.object(MLBF5HistorySource, "_schedule_payload", return_value=payload):
            got = source._schedule_payload(team_id=112, target_date=date(2026, 9, 29))

        innings = got["dates"][0]["games"][0]["linescore"]["innings"]
        self.assertEqual(innings[0]["teams"]["away"]["runs"], 1)
        self.assertEqual(innings[0]["teams"]["home"]["runs"], 0)
        self.assertEqual(innings[1]["teams"]["away"]["runs"], 0)
        self.assertEqual(innings[1]["teams"]["home"]["runs"], 1)

    @staticmethod
    def _inning_matchup_payload():
        features = {
            "away_f5_runs_for": [2, 3, 1, 0, 4, 2, 1, 3, 2, 5],
            "away_f5_runs_against": [1, 1, 2, 2, 3, 0, 2, 1, 4, 2],
            "home_f5_runs_for": [1, 2, 2, 3, 0, 4, 1, 2, 3, 1],
            "home_f5_runs_against": [2, 1, 0, 2, 1, 3, 1, 4, 2, 2],
            "away_first_inning_runs_for": [0, 0, 1, 0, 0, 0, 1, 0, 0, 0],
            "away_first_inning_runs_against": [0, 1, 0, 0, 0, 0, 0, 1, 0, 0],
            "home_first_inning_runs_for": [0, 1, 0, 0, 0, 1, 0, 0, 0, 0],
            "home_first_inning_runs_against": [0, 0, 0, 1, 0, 0, 0, 0, 1, 0],
            "league_f5_pmf": {"0": 0.10, "1": 0.20, "2": 0.30, "3": 0.20, "4": 0.10, "5": 0.10},
            "league_first_inning_scoreless_rate": 0.72,
            "league_prior_halves": 1000,
            "league_prior_strength": 30,
        }
        return {
            "feature_version": "mlb_f5_actual_innings_v3_m30_league_prior",
            "feature_source_hash": "a" * 64,
            "away_history_games": 10,
            "home_history_games": 10,
            "league_prior_source_hash": "b" * 64,
            "features": features,
        }

    def test_f5_feature_row_uses_complete_strict_prior_matchup_state(self):
        payload = self._inning_matchup_payload()
        source = self._source()
        with patch.object(_StatsAPIF5ShapeAdapter, "matchup_features", return_value=payload):
            row = source.feature_row(
                game_pk=849843,
                market="F5_TOTALS",
                entity_id="849843",
                target_date=date(2026, 9, 29),
                away_team_id=112,
                home_team_id=135,
            )

        self.assertEqual(row["features"], payload["features"])
        self.assertEqual(row["feature_source_hash"], "a" * 64)
        self.assertEqual(row["joint_feature_version"], payload["feature_version"])
        self.assertEqual(row["league_prior_source_hash"], "b" * 64)
        self.assertEqual(len(row["source_subset_hash"]), 64)

    def test_yrfi_feature_row_reaches_validated_first_inning_engine(self):
        payload = self._inning_matchup_payload()
        source = self._source()
        with patch.object(_StatsAPIF5ShapeAdapter, "matchup_features", return_value=payload):
            row = source.feature_row(
                game_pk=849843,
                market="YRFI",
                entity_id="849843",
                target_date=date(2026, 9, 29),
                away_team_id=112,
                home_team_id=135,
            )

        model_input = _model_input(
            game=SimpleNamespace(game_pk=849843),
            quote={"market": "YRFI", "entity_id": "849843", "line": 0.5, "side": "YES"},
            feature=row,
            require_confirmed_lineup=False,
        )
        self.assertEqual(model_input["feature_source_hash"], "a" * 64)
        self.assertEqual(model_input["features"], payload["features"])
        result = generic_market_engine_adapter(model_input)
        self.assertGreater(result["model_p"], 0.0)
        self.assertLess(result["model_p"], 1.0)
        self.assertEqual(result["engine_version"], "mlb_first_inning_empirical_jeffreys_m30_v2")

    def test_pitcher_record_win_uses_state_builder_and_adapter(self):
        built = {
            "feature_version": "mlb_pitcher_record_win_features_v2",
            "team_id": 112,
            "team_side": "AWAY",
            "starter_outs_history": [15] * 10,
            "f5_features": {},
            "f5_feature_source_hash": "a" * 64,
            "pitcher_source_hash": "b" * 64,
            "game_source_hash": "c" * 64,
            "credit_path_source_hash": "d" * 64,
            "post_f5_credit_paths": {"LEAD": [15] * 10, "TIE": [None] * 10, "TRAIL": [None] * 10},
        }
        source = self._source()
        with patch(
            "sportsedge.mlb_all_market_features.build_pitcher_record_win_features",
            return_value=built,
        ) as build:
            row = source.feature_row(
                game_pk=849843,
                market="PITCHER_RECORD_WIN",
                entity_id="571510",
                target_date=date(2026, 9, 29),
                away_team_id=112,
                home_team_id=135,
                player_id=571510,
                away_pitcher_id=571510,
                home_pitcher_id=650633,
            )

        self.assertEqual(row["team_id"], 112)
        self.assertEqual(row["team_side"], "AWAY")
        self.assertEqual(row["features"], built)
        self.assertEqual(row["joint_feature_version"], built["feature_version"])
        self.assertEqual(len(row["source_subset_hash"]), 64)
        self.assertIsInstance(build.call_args.kwargs["f5_source"], _StatsAPIF5ShapeAdapter)


if __name__ == "__main__":
    unittest.main()
