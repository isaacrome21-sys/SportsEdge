from __future__ import annotations

from datetime import datetime, timezone
import json

from sportsedge.mlb_umpire_source import (
    acquire_umpire_context,
    home_plate_from_live,
    shrink_tendencies,
)


TEST_CONFIG = {
    "schema_version": "mlb_umpire_prior_test_v1",
    "league_prior": {
        "runs_per_game": 8.9,
        "strikeouts_per_game": 16.72,
        "walks_per_game": 6.32,
    },
    "prior_equivalent_games": 8,
    "min_home_plate_games": 8,
    "history_days": 365,
}


class _Response:
    def __init__(self, payload: dict):
        self._raw = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._raw


def test_live_boxscore_home_plate_assignment_is_preferred():
    live_payload = {
        "liveData": {
            "boxscore": {
                "officials": [
                    {"official": {"id": 77, "fullName": "HP Ump"}, "officialType": "Home Plate"},
                    {"official": {"id": 78, "fullName": "First Ump"}, "officialType": "First Base"},
                ]
            }
        }
    }
    assert home_plate_from_live(live_payload) == {
        "umpire_id": 77,
        "umpire_name": "HP Ump",
        "official_type": "Home Plate",
    }


def test_under_eight_games_forces_exact_zero_delta():
    rows = [
        {"runs": 12.0, "strikeouts": 20.0, "walks": 9.0}
        for _ in range(7)
    ]
    result = shrink_tendencies(rows, prior_config=TEST_CONFIG)
    assert result["home_plate_games"] == 7
    assert result["sample_gate"] == "BELOW_MIN_GAMES_ZERO_DELTA"
    assert result["deltas"] == {
        "runs_delta": 0.0,
        "strikeouts_delta": 0.0,
        "walks_delta": 0.0,
    }


def test_eight_games_apply_empirical_bayes_shrinkage():
    rows = [
        {"runs": 10.9, "strikeouts": 18.72, "walks": 8.32}
        for _ in range(8)
    ]
    result = shrink_tendencies(rows, prior_config=TEST_CONFIG)
    assert result["sample_gate"] == "PASS"
    assert result["deltas"] == {
        "runs_delta": 1.0,
        "strikeouts_delta": 1.0,
        "walks_delta": 1.0,
    }


def test_schedule_hydrate_is_fallback_when_live_official_missing():
    schedule = {
        "dates": [
            {
                "date": "2026-09-22",
                "games": [
                    {
                        "gamePk": 999004,
                        "officials": [
                            {"official": {"id": 91, "fullName": "Fallback HP"}, "officialType": "Home Plate"}
                        ],
                    }
                ],
            }
        ]
    }

    calls = []

    def opener(req, timeout=30):
        url = getattr(req, "full_url", str(req))
        calls.append(url)
        assert "hydrate=officials" in url
        return _Response(schedule)

    result = acquire_umpire_context(
        game_pk=999004,
        as_of=datetime(2026, 9, 22, 15, 0, tzinfo=timezone.utc),
        live_payload={},
        official_date="2026-09-22",
        opener=opener,
        history_rows=[],
        prior_config=TEST_CONFIG,
    )

    assert len(calls) == 1
    assert result["assignment_source"] == "SCHEDULE_HYDRATE_OFFICIALS"
    assert result["assignment"]["umpire_id"] == 91
    assert result["tendencies"]["sample_gate"] == "BELOW_MIN_GAMES_ZERO_DELTA"
    assert result["model_p_eligible"] is False
