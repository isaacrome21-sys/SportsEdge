from __future__ import annotations

import unittest

from sportsedge.sports.cfb.reconstructed_selection import (
    CFBReconstructedSelectionError,
    RECONSTRUCTED_PROVENANCE,
    build_selection_bundle_manifest,
    materialize_reconstructed_selection_rows,
)
from sportsedge.sports.cfb.source import CFBTeamMetrics


def metric(team: str, season: int, through_week: int, source: str) -> CFBTeamMetrics:
    return CFBTeamMetrics(
        team=team,
        season=season,
        through_week=through_week,
        sample_source=source,
        off_ppa_rush=0.1,
        off_ppa_dropback=0.2,
        def_ppa_rush_allowed=0.3,
        def_ppa_dropback_allowed=0.4,
        off_success_rate=0.5,
        def_success_rate_allowed=0.6,
        standard_down_ppa=0.7,
        passing_down_success_rate=0.8,
        eckel_rate=0.9,
        points_per_eckel=1.0,
        points_per_drive=1.1,
        net_field_position=1.2,
        explosive_rate=1.3,
        # Actual reconstruction time is deliberately after the historical game.
        feature_asof_ts="2026-09-18T12:00:00+00:00",
    )


class TestCFBReconstructedSelectionMaterializer(unittest.TestCase):
    def setUp(self):
        self.games = [
            {
                "game_id": "1",
                "season": 2015,
                "week": 1,
                "start_ts": "2015-09-05T17:00:00+00:00",
                "home_team": "Home",
                "away_team": "Away",
                "neutral_site": False,
                "home_score": 31,
                "away_score": 20,
            }
        ]
        self.metrics = [
            metric("Home", 2014, 99, "PRIOR_SEASON_FALLBACK"),
            metric("Away", 2014, 99, "PRIOR_SEASON_FALLBACK"),
        ]
        self.weather = {
            "1": {
                "source": "CFBD_GAMES_WEATHER_RECONSTRUCTED_CURRENT_PROVIDER_VINTAGE",
                "retrieved_at_utc": "2026-09-18T12:00:00+00:00",
                "gameIndoors": False,
                "windSpeed": 8.0,
                "temperature": 72.0,
            }
        }
        self.membership = {2015: [{"school": "Home"}, {"school": "Away"}]}

    def test_reconstructed_timestamp_after_old_kickoff_is_not_mislabeled_pit(self):
        rows = materialize_reconstructed_selection_rows(
            games=self.games,
            metrics=self.metrics,
            weather_by_game=self.weather,
            fbs_membership_by_season=self.membership,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["provenance_class"], RECONSTRUCTED_PROVENANCE)
        self.assertFalse(rows[0]["historical_pit_created"])
        self.assertEqual(rows[0]["home_current_metrics"]["team"], "Home")
        self.assertEqual(rows[0]["home_current_metrics"]["games_in_sample"], 0)
        self.assertEqual(rows[0]["home_prior_metrics"]["season"], 2014)
        self.assertEqual(rows[0]["weather"]["provenance_class"], RECONSTRUCTED_PROVENANCE)

    def test_market_data_is_rejected(self):
        games = [dict(self.games[0], spread=-3.5)]
        with self.assertRaisesRegex(
            CFBReconstructedSelectionError,
            "CFB_RECONSTRUCTED_MARKET_DATA_PROHIBITED",
        ):
            materialize_reconstructed_selection_rows(
                games=games,
                metrics=self.metrics,
                weather_by_game=self.weather,
                fbs_membership_by_season=self.membership,
            )

    def test_non_fbs_opponent_fails_closed(self):
        with self.assertRaises(Exception):
            materialize_reconstructed_selection_rows(
                games=self.games,
                metrics=self.metrics,
                weather_by_game=self.weather,
                fbs_membership_by_season={2015: [{"school": "Home"}]},
            )

    def test_bundle_manifest_is_selection_only_zero_authority(self):
        rows = [
            {
                "season": season,
                "game_id": str(season),
                "provenance_class": RECONSTRUCTED_PROVENANCE,
                "historical_pit_created": False,
            }
            for season in range(2015, 2026)
        ]
        policy = {
            "feature_semantics": "AS_OF_WEEK_MATCHED_V1",
            "feature_value_source_contract": "CFBD_STATS_SEASON_ADVANCED_ENDWEEK_V1",
            "provider_metric_model_vintage": "UNKNOWN_CURRENT_PROVIDER_VINTAGE",
            "provider_metric_materialization_mode": "UNKNOWN_PROVIDER_IMPLEMENTATION",
        }
        manifest = build_selection_bundle_manifest(
            rows=rows,
            source_manifest={"responses": [{"response_sha256": "a" * 64}]},
            policy=policy,
            predictive_code_manifest_sha256="b" * 64,
            acquisition_code_manifest_sha256="c" * 64,
            weather_source_contract="CFBD_GAMES_WEATHER_RECONSTRUCTED_CURRENT_PROVIDER_VINTAGE",
        )
        self.assertEqual(manifest["status"], "READY_FOR_CANDIDATE_EVALUATION")
        self.assertEqual(manifest["start_season"], 2015)
        self.assertEqual(manifest["end_season"], 2025)
        self.assertFalse(manifest["historical_pit_created"])
        self.assertFalse(manifest["attempt_consumed"])
        self.assertFalse(manifest["evaluation_performed"])
        self.assertFalse(manifest["model_p_created"])
        self.assertFalse(manifest["promotion_authority"])
        self.assertFalse(manifest["eligibility_changed"])
        self.assertFalse(manifest["official_authority"])
        self.assertEqual(len(manifest["selection_rows_sha256"]), 64)
        self.assertEqual(len(manifest["source_manifest_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
