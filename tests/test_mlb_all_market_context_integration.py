from datetime import date, datetime, timezone

from sportsedge.mlb_all_market_features import MLBAllMarketHistorySource
from sportsedge.mlb_context_artifact import build_candidate_artifact


class _Source(MLBAllMarketHistorySource):
    def defense_blended_team_means(self, *, away_team_id, home_team_id, target_date):
        return 4.0, 4.0, {"fixture": True}

    def _attach_starter_effects(
        self, row, *, away_pitcher_id, home_pitcher_id, target_date
    ):
        return None


def _context():
    return {
        "game_pk": 77,
        "as_of_utc": "2026-10-07T17:00:00+00:00",
        "starters": {
            "status": "AVAILABLE",
            "probable_pitchers": {
                "away": {"player_id": 11},
                "home": {"player_id": 22},
            },
        },
        "lineups": {
            "status": "AVAILABLE",
            "complete_by_side": {"away": True, "home": True},
        },
        "injuries_scratches": {"status": "AVAILABLE"},
        "umpire": {"status": "AVAILABLE", "home_plate_games": 30},
        "statcast": {"status": "AVAILABLE"},
        "park_venue": {"status": "AVAILABLE", "roof_type": "Open"},
        "weather_roof": {"status": "AVAILABLE", "temperature_f": 80},
        "bullpen_workload": {"status": "AVAILABLE"},
    }


def _source():
    return _Source(retrieved_at=datetime(2026, 10, 7, 17, tzinfo=timezone.utc))


def test_context_without_validated_artifact_is_exact_baseline():
    row = _source().feature_row(
        game_pk=77,
        market="TOTALS",
        entity_id="77",
        target_date=date(2026, 10, 7),
        away_team_id=1,
        home_team_id=2,
        pregame_context=_context(),
    )
    assert row["away_mean_runs"] == 4.0
    assert row["home_mean_runs"] == 4.0
    assert row["context_run_adjustment"]["status"] == "BASELINE"
    assert row["pregame_context_price_blind"] is True


def test_validated_artifact_is_the_only_context_path_that_moves_means():
    artifact = build_candidate_artifact(
        {"temperature_f": 0.001},
        {"status": "VALIDATED", "holdout_games": 200},
        source_manifest={"pit_strict": True, "contains_sportsbook_prices": False},
        max_abs_log_multiplier=0.2,
    )
    row = _source().feature_row(
        game_pk=77,
        market="TOTALS",
        entity_id="77",
        target_date=date(2026, 10, 7),
        away_team_id=1,
        home_team_id=2,
        pregame_context=_context(),
        context_artifact=artifact,
    )
    assert row["away_mean_runs"] > 4.0
    assert row["home_mean_runs"] > 4.0
    assert row["context_run_adjustment"]["status"] == "CONTEXT_ADJUSTED"
