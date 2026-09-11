from sportsedge.sports.cfb.depth_chart_source import (
    CFBDepthSourceError,
    require_player_depth_usable,
    validate_depth_snapshot,
)


def _snapshot():
    return {
        "source_id": "TWO_DEEP_PROJECTED_TWO_DEEP",
        "source_kind": "PROJECTED_TWO_DEEP",
        "retrieved_at": "2026-09-11T15:00:00Z",
        "source_updated_at": "2026-09-10T00:00:00Z",
        "source_url": "https://www.thetwodeep.com/college/alabama",
        "content_sha256": "a" * 64,
        "team_id": "alabama",
        "players": [
            {
                "player_id": "daniel-hill",
                "position": "RB",
                "depth_rank": 1,
                "unavailable": False,
            }
        ],
    }


def test_snapshot_accepts_fresh_projected_depth_input_without_promotion_authority():
    row = validate_depth_snapshot(
        _snapshot(),
        previous_game_end="2026-09-06T03:00:00Z",
        expected_content_sha256="a" * 64,
    )
    assert row["promotion_authority"] is False
    assert row["model_p_authority"] is False


def test_snapshot_blocks_stale_chart():
    row = _snapshot()
    row["source_updated_at"] = "2026-09-05T00:00:00Z"
    try:
        validate_depth_snapshot(row, previous_game_end="2026-09-06T03:00:00Z")
    except CFBDepthSourceError as exc:
        assert str(exc) == "DEPTH_CHART_STALE"
    else:
        raise AssertionError("stale depth chart must fail closed")


def test_snapshot_blocks_hash_mismatch():
    try:
        validate_depth_snapshot(
            _snapshot(),
            previous_game_end="2026-09-06T03:00:00Z",
            expected_content_sha256="b" * 64,
        )
    except CFBDepthSourceError as exc:
        assert str(exc) == "CFB_DEPTH_CONTENT_SHA256_MISMATCH"
    else:
        raise AssertionError("tampered snapshot must fail closed")


def test_unavailable_player_blocks():
    player = _snapshot()["players"][0]
    player["unavailable"] = True
    try:
        require_player_depth_usable(
            primary_player=player,
            corroborating_starter_player_id="daniel-hill",
        )
    except CFBDepthSourceError as exc:
        assert str(exc) == "PLAYER_UNAVAILABLE"
    else:
        raise AssertionError("unavailable player must fail closed")


def test_starter_conflict_blocks():
    player = _snapshot()["players"][0]
    try:
        require_player_depth_usable(
            primary_player=player,
            corroborating_starter_player_id="other-player",
        )
    except CFBDepthSourceError as exc:
        assert str(exc) == "STARTER_CONFLICT"
    else:
        raise AssertionError("starter disagreement must fail closed")
