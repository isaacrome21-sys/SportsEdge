import pytest


def _snapshot(team, asof, **extra):
    row = {
        "team": team,
        "feature_asof_ts": asof,
        "off_epa": 0.1,
        "def_epa": -0.05,
        "pass_epa": 0.12,
        "rush_epa": 0.03,
        "pressure_for": 0.25,
        "pressure_allowed": 0.20,
        "success_rate": 0.45,
        "explosive_rate": 0.11,
    }
    row.update(extra)
    return row


def test_point_in_time_join_uses_latest_strictly_prior_snapshot():
    from sportsedge.sports.nfl.point_in_time import build_game_feature_rows

    games = [{
        "game_id": "2025_03_A_B",
        "season": 2025,
        "week": 3,
        "game_start_ts": "2025-09-21T17:00:00+00:00",
        "home_team": "A",
        "away_team": "B",
    }]
    snapshots = [
        _snapshot("A", "2025-09-10T12:00:00+00:00", off_epa=0.10),
        _snapshot("A", "2025-09-20T12:00:00+00:00", off_epa=0.20),
        _snapshot("A", "2025-09-21T18:00:00+00:00", off_epa=9.99),
        _snapshot("B", "2025-09-19T12:00:00+00:00", off_epa=-0.10),
    ]
    rows = build_game_feature_rows(games, snapshots)
    assert len(rows) == 2
    home = next(r for r in rows if r["side"] == "home")
    assert home["team"] == "A"
    assert home["off_epa"] == 0.20
    assert home["feature_asof_ts"] == "2025-09-20T12:00:00+00:00"


def test_snapshot_at_kickoff_is_rejected_not_joined():
    from sportsedge.sports.nfl.point_in_time import build_game_feature_rows

    games = [{
        "game_id": "g1", "season": 2025, "week": 1,
        "game_start_ts": "2025-09-07T17:00:00+00:00",
        "home_team": "A", "away_team": "B",
    }]
    snapshots = [
        _snapshot("A", "2025-09-07T17:00:00+00:00"),
        _snapshot("B", "2025-09-06T17:00:00+00:00"),
    ]
    with pytest.raises(ValueError, match="POINT_IN_TIME_SNAPSHOT_MISSING:A"):
        build_game_feature_rows(games, snapshots)


def test_market_or_outcome_fields_are_forbidden_in_snapshot():
    from sportsedge.sports.nfl.point_in_time import build_game_feature_rows

    games = [{
        "game_id": "g1", "season": 2025, "week": 1,
        "game_start_ts": "2025-09-07T17:00:00+00:00",
        "home_team": "A", "away_team": "B",
    }]
    snapshots = [
        _snapshot("A", "2025-09-06T17:00:00+00:00", closing_spread=-3.5),
        _snapshot("B", "2025-09-06T17:00:00+00:00"),
    ]
    with pytest.raises(ValueError, match="POINT_IN_TIME_PROHIBITED_FIELD"):
        build_game_feature_rows(games, snapshots)


def test_cache_manifest_is_hash_bound_and_order_stable():
    from sportsedge.sports.nfl.point_in_time import build_cache_manifest

    rows = [
        {"game_id": "b", "team": "B", "feature_asof_ts": "2025-09-02T00:00:00+00:00", "game_start_ts": "2025-09-03T00:00:00+00:00"},
        {"game_id": "a", "team": "A", "feature_asof_ts": "2025-09-01T00:00:00+00:00", "game_start_ts": "2025-09-03T00:00:00+00:00"},
    ]
    first = build_cache_manifest(rows, source_sha256="a" * 64, source_name="nflverse-derived-team-week")
    second = build_cache_manifest(list(reversed(rows)), source_sha256="a" * 64, source_name="nflverse-derived-team-week")
    assert first["cache_sha256"] == second["cache_sha256"]
    assert first["row_count"] == 2
    assert first["provenance"] == "POINT_IN_TIME_REAL_HISTORY"


def test_manifest_rejects_bad_source_hash():
    from sportsedge.sports.nfl.point_in_time import build_cache_manifest

    with pytest.raises(ValueError, match="SOURCE_SHA256_INVALID"):
        build_cache_manifest([], source_sha256="not-a-hash", source_name="x")
