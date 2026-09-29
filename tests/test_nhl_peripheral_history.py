from sportsedge.sports.nhl.peripheral_history import (
    NHLPlayerPeripheralObservation,
    extract_player_peripheral_observations,
    fit_empirical_peripheral_roles,
    fit_team_peripheral_parameters,
)


def _payload():
    return {
        "id": 2025020001,
        "gameState": "OFF",
        "startTimeUTC": "2025-10-01T23:00:00Z",
        "homeTeam": {"id": 1},
        "awayTeam": {"id": 2},
        "boxscore": {
            "playerByGameStats": {
                "homeTeam": {
                    "forwards": [
                        {"playerId": 101, "hits": 3, "blockedShots": 1, "toi": "18:30"},
                        {"playerId": 102, "hits": 1, "blockedShots": 0, "toi": "15:00"},
                    ],
                    "defense": [
                        {"playerId": 103, "hits": 2, "blockedShots": 4, "toi": "22:10"},
                    ],
                },
                "awayTeam": {
                    "forwards": [
                        {"playerId": 201, "hits": 2, "blockedShots": 1, "toi": "17:00"},
                    ],
                    "defense": [
                        {"playerId": 202, "hits": 1, "blockedShots": 3, "toi": "23:00"},
                    ],
                },
            }
        },
    }


def test_extract_official_peripheral_rows_from_boxscore_schema():
    rows = extract_player_peripheral_observations(
        _payload(),
        captured_at="2026-09-29T20:00:00+00:00",
        raw_sha256="a" * 64,
    )
    assert len(rows) == 5
    p103 = next(r for r in rows if r.player_id == "103")
    assert p103.team_id == "1"
    assert p103.team_side == "HOME"
    assert p103.blocks == 4
    assert p103.hits == 2
    assert p103.toi_seconds == 22 * 60 + 10


def _obs(game_id: str, start: str, player: str, blocks: int, hits: int) -> NHLPlayerPeripheralObservation:
    return NHLPlayerPeripheralObservation(
        game_id=game_id,
        player_id=player,
        team_id="1",
        team_side="HOME",
        start_time_utc=start,
        captured_at="2027-01-01T00:00:00+00:00",
        hits=hits,
        blocks=blocks,
        toi_seconds=1200,
        source_uri=f"https://api-web.nhle.com/v1/gamecenter/{game_id}/boxscore",
        source_raw_sha256=("b" if player == "101" else "c") * 64,
        source_version="nhl-web-api-v1",
    )


def test_fit_peripheral_team_and_roles_excludes_future_games():
    rows = (
        _obs("2025020001", "2025-10-01T23:00:00+00:00", "101", 2, 3),
        _obs("2025020001", "2025-10-01T23:00:00+00:00", "102", 1, 1),
        _obs("2025020002", "2025-10-03T23:00:00+00:00", "101", 4, 1),
        _obs("2025020002", "2025-10-03T23:00:00+00:00", "102", 1, 3),
        _obs("2026020001", "2026-10-03T23:00:00+00:00", "101", 99, 99),
        _obs("2026020001", "2026-10-03T23:00:00+00:00", "102", 99, 99),
    )
    cutoff = "2026-09-29T12:00:00+00:00"
    params = fit_team_peripheral_parameters(rows, cutoff=cutoff, team_id="1", version="team-v1", min_games=2)
    assert params.expected_blocks == 4.0
    assert params.expected_hits == 4.0

    roles = fit_empirical_peripheral_roles(
        rows,
        cutoff=cutoff,
        team_id="1",
        team_side="HOME",
        active_player_ids=("101", "102"),
        version="role-v1",
        min_games=2,
        lineup_status="CONFIRMED",
    )
    by_id = {r.player_id: r for r in roles}
    assert by_id["101"].block_weight == 3.0
    assert by_id["101"].hit_weight == 2.0
    assert by_id["102"].block_weight == 1.0
    assert by_id["102"].hit_weight == 2.0


def test_role_fit_fails_closed_on_missing_active_player_history():
    rows = (_obs("2025020001", "2025-10-01T23:00:00+00:00", "101", 2, 3),)
    try:
        fit_empirical_peripheral_roles(
            rows,
            cutoff="2026-09-29T12:00:00+00:00",
            team_id="1",
            team_side="HOME",
            active_player_ids=("101", "999"),
            version="role-v1",
            min_games=1,
        )
    except ValueError as exc:
        assert "insufficient peripheral history" in str(exc)
    else:
        raise AssertionError("missing active-player history must fail closed")
