from datetime import date, datetime, timezone

import pytest

from sportsedge.mlb_pitcher_k_historical_materializer import (
    HistoricalStatcastArchive,
    PitcherKHistoricalMaterializerError,
    PitcherKTarget,
    _Pitch,
    combine_seasons,
    targets_from_schedule,
)


def _schedule():
    return {
        "dates": [
            {
                "date": "2025-06-01",
                "games": [
                    {
                        "gamePk": 777,
                        "gameType": "R",
                        "officialDate": "2025-06-01",
                        "status": {"abstractGameState": "Final"},
                        "teams": {
                            "away": {
                                "team": {"id": 10},
                                "probablePitcher": {"id": 501},
                            },
                            "home": {
                                "team": {"id": 20},
                                "probablePitcher": {"id": 601},
                            },
                        },
                    }
                ],
            }
        ]
    }


def test_schedule_targets_bind_both_sides_and_opponents():
    got = targets_from_schedule(_schedule(), season=2025)
    assert [(x.pitcher_id, x.team_id, x.opponent_id) for x in got] == [
        (501, 10, 20),
        (601, 20, 10),
    ]
    assert all(x.game_id == 777 for x in got)


def test_schedule_missing_probable_pitcher_fails_closed_by_omission():
    payload = _schedule()
    del payload["dates"][0]["games"][0]["teams"]["home"]["probablePitcher"]
    got = targets_from_schedule(payload, season=2025)
    assert [x.pitcher_id for x in got] == [501]


def test_local_statcast_window_excludes_target_date_and_future_rows():
    rows = {
        501: [
            _Pitch(date(2025, 5, 10), "swinging_strike", 12, "R"),
            _Pitch(date(2025, 5, 11), "foul", 12, "R"),
            _Pitch(date(2025, 5, 12), "swinging_strike", 5, "R"),
            _Pitch(date(2025, 6, 1), "swinging_strike", 12, "R"),
            _Pitch(date(2025, 6, 2), "swinging_strike", 12, "R"),
        ]
    }
    archive = HistoricalStatcastArchive(
        rows, retrieved_at=datetime(2026, 10, 6, tzinfo=timezone.utc)
    )
    context, receipt = archive.pitcher_context(
        pitcher_id=501, target_date=date(2025, 6, 1)
    )
    assert context["swings"] == 3
    assert context["whiffs"] == 2
    assert context["out_of_zone_pitches"] == 2
    assert context["chases"] == 2
    assert context["window_end"] == "2025-06-01"
    assert receipt["same_day_rows_included"] is False
    assert receipt["future_rows_included"] is False
    assert receipt["forward_evidence_eligible"] is False


def test_statcast_archive_rejects_empty_skill_window():
    archive = HistoricalStatcastArchive(
        {}, retrieved_at=datetime(2026, 10, 6, tzinfo=timezone.utc)
    )
    with pytest.raises(PitcherKHistoricalMaterializerError, match="window empty"):
        archive.pitcher_context(pitcher_id=501, target_date=date(2025, 6, 1))


def test_combined_artifact_requires_exact_frozen_seasons_and_zero_authority():
    parts = []
    for season in (2023, 2024, 2025):
        parts.append(
            {
                "season": season,
                "target_count": 1,
                "eligible_row_count": 1,
                "excluded_row_count": 0,
                "exclusions": {},
                "rows": [{"season": season}],
            }
        )
    got = combine_seasons(parts)
    assert got["seasons"] == [2023, 2024, 2025]
    assert got["row_count"] == 3
    assert got["forward_evidence_eligible"] is False
    assert not any(got["authority"].values())


def test_duplicate_schedule_target_is_collapsed_only_when_identical():
    payload = _schedule()
    payload["dates"].append({
        "date": "2025-06-01",
        "games": [dict(payload["dates"][0]["games"][0])],
    })
    got = targets_from_schedule(payload, season=2025)
    assert [(x.game_id, x.pitcher_id) for x in got] == [(777, 501), (777, 601)]


def test_conflicting_duplicate_schedule_target_fails_closed():
    payload = _schedule()
    duplicate = dict(payload["dates"][0]["games"][0])
    duplicate["teams"] = {
        "away": {
            "team": {"id": 10},
            "probablePitcher": {"id": 501},
        },
        "home": {
            "team": {"id": 99},
            "probablePitcher": {"id": 601},
        },
    }
    payload["dates"].append({"date": "2025-06-01", "games": [duplicate]})
    with pytest.raises(PitcherKHistoricalMaterializerError, match="conflicting duplicate schedule target"):
        targets_from_schedule(payload, season=2025)


def test_combine_seasons_collapses_only_byte_identical_row_duplicates():
    base_row = {
        "season": 2025,
        "target_date": "2025-06-01",
        "game_id": 777,
        "pitcher_id": "501",
        "candidate": {"x": 1},
    }
    parts = [
        {"season": 2023, "target_count": 1, "eligible_row_count": 1, "excluded_row_count": 0, "exclusions": {}, "rows": [{"season": 2023, "target_date": "2023-06-01", "game_id": 1, "pitcher_id": "1"}]},
        {"season": 2024, "target_count": 1, "eligible_row_count": 1, "excluded_row_count": 0, "exclusions": {}, "rows": [{"season": 2024, "target_date": "2024-06-01", "game_id": 2, "pitcher_id": "2"}]},
        {"season": 2025, "target_count": 2, "eligible_row_count": 2, "excluded_row_count": 0, "exclusions": {}, "rows": [dict(base_row), dict(base_row)]},
    ]
    got = combine_seasons(parts)
    assert got["row_count"] == 3
    assert got["duplicate_rows_collapsed"] == 1


def test_combine_seasons_rejects_conflicting_duplicate_rows():
    a = {"season": 2025, "target_date": "2025-06-01", "game_id": 777, "pitcher_id": "501", "candidate": {"x": 1}}
    b = {"season": 2025, "target_date": "2025-06-01", "game_id": 777, "pitcher_id": "501", "candidate": {"x": 2}}
    parts = [
        {"season": 2023, "target_count": 1, "eligible_row_count": 1, "excluded_row_count": 0, "exclusions": {}, "rows": [{"season": 2023, "target_date": "2023-06-01", "game_id": 1, "pitcher_id": "1"}]},
        {"season": 2024, "target_count": 1, "eligible_row_count": 1, "excluded_row_count": 0, "exclusions": {}, "rows": [{"season": 2024, "target_date": "2024-06-01", "game_id": 2, "pitcher_id": "2"}]},
        {"season": 2025, "target_count": 2, "eligible_row_count": 2, "excluded_row_count": 0, "exclusions": {}, "rows": [a, b]},
    ]
    with pytest.raises(PitcherKHistoricalMaterializerError, match="conflicting duplicate evaluation row"):
        combine_seasons(parts)
