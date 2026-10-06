from datetime import date, datetime, timezone

import pytest

from sportsedge.mlb_pitcher_k_historical_materializer import (
    HistoricalStatcastArchive,
    PitcherKHistoricalMaterializerError,
    PitcherKTarget,
    _Pitch,
    combine_seasons,
    materialize_target,
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


def test_materialize_target_rejects_equal_count_different_start_identity(monkeypatch):
    target = PitcherKTarget(
        season=2025,
        target_date=date(2025, 6, 1),
        game_id=777,
        pitcher_id=501,
        team_id=10,
        opponent_id=20,
        away_team_id=10,
        home_team_id=20,
    )
    prior = []
    aligned = []
    for i in range(5):
        d = date(2025, 5, 1 + i)
        stat = {
            "gamesStarted": 1,
            "inningsPitched": "6.0",
            "strikeOuts": 6,
            "earnedRuns": 2,
            "hits": 5,
            "baseOnBalls": 2,
            "battersFaced": 24,
            "numberOfPitches": 90,
        }
        prior.append({"date": d, "game_pk": 100 + i, "opponent_id": 20, "stat": stat})
        aligned.append(({"strikeouts": 6, "outs": 18, "earned_runs": 2, "hits_allowed": 5, "walks_allowed": 2}, d, 20, 100 + i))
    aligned[-1] = (aligned[-1][0], aligned[-1][1], aligned[-1][2], 999)

    class Source:
        def player_rows(self, **kwargs):
            return prior
        def _opp_k_payload(self, **kwargs):
            return ({"market": "PITCHER_K", "opponent_team_id": 20, "target_rel": 1.0}, None)
        def pitcher_joint_history(self, **kwargs):
            return [x[0] for x in aligned]
        def _pitcher_start_rows_pk(self, **kwargs):
            return aligned

    class Archive:
        def pitcher_context(self, **kwargs):
            return (
                {"entity_id": "501", "swings": 10, "whiffs": 3, "whiff_rate": 0.3,
                 "out_of_zone_pitches": 10, "chases": 3, "chase_rate": 0.3,
                 "pitcher_hand": "R", "window_start": "2025-05-03", "window_end": "2025-06-01"},
                {"schema": "MLB_PITCHER_K_PROVENANCE_V1", "source": "BASEBALL_SAVANT_STATCAST",
                 "mode": "HISTORICAL_RECONSTRUCTION", "target_date": "2025-06-01",
                 "window_start": "2025-05-03", "query_end_exclusive": "2025-06-01",
                 "retrieved_at": "2026-10-06T00:00:00+00:00", "raw_pitch_rows": 30,
                 "raw_pitch_rows_scope": "TARGET_PITCHER_WINDOW", "same_day_rows_included": False,
                 "future_rows_included": False, "historical_reconstruction": True, "backfill": True,
                 "forward_evidence_eligible": False, "promotion_authority": False,
                 "evaluation_use": "FROZEN_CANDIDATE_TEST"},
            )

    with pytest.raises(PitcherKHistoricalMaterializerError, match="identity mismatch"):
        materialize_target(Source(), Archive(), target)
