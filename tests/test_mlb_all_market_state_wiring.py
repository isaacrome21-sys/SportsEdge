from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch

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

    def test_f5_feature_row_nests_strict_prior_state_for_engine(self):
        base_row = {
            "generic_feature_version": "test",
            "game_pk": 849843,
            "market": "F5_TOTALS",
            "entity_id": "849843",
            "retrieved_at": "2026-09-29T21:52:00+00:00",
            "asof": "2026-09-29T21:52:00+00:00",
            "source": "MLB_STATSAPI_CHRONOLOGICAL_GAMELOG",
            "source_subset_hash": "old",
            "away_f5_runs_for": [2, 3, 1, 0, 4, 2, 1, 3, 2, 5],
            "away_f5_runs_against": [1, 1, 2, 2, 3, 0, 2, 1, 4, 2],
            "home_f5_runs_for": [1, 2, 2, 3, 0, 4, 1, 2, 3, 1],
            "home_f5_runs_against": [2, 1, 0, 2, 1, 3, 1, 4, 2, 2],
        }
        source = self._source()
        with patch.object(MLBGenericHistorySource, "feature_row", return_value=base_row):
            row = source.feature_row(
                game_pk=849843,
                market="F5_TOTALS",
                entity_id="849843",
                target_date=date(2026, 9, 29),
                away_team_id=112,
                home_team_id=135,
            )

        self.assertEqual(row["features"]["away_f5_runs_for"], base_row["away_f5_runs_for"])
        self.assertEqual(row["features"]["home_f5_runs_against"], base_row["home_f5_runs_against"])
        self.assertEqual(row["joint_feature_version"], "mlb_f5_strict_prior_linescore_v1")
        self.assertEqual(len(row["source_subset_hash"]), 64)
        self.assertNotEqual(row["source_subset_hash"], "old")

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
