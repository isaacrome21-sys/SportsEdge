from sportsedge.sports.nhl.event_binding import simulate_bound_roster_events
from sportsedge.sports.nhl.official_role_source import build_official_player_role_observations
from sportsedge.sports.nhl.role_binding import bind_historical_roles
from sportsedge.sports.nhl.role_history import fit_empirical_role_shares
from sportsedge.sports.nhl.roster_events import roster_event_over
from sportsedge.sports.nhl.simulation import NHLGamePaths


def boxscore():
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
                        {"playerId": 101, "shots": 5},
                        {"playerId": 102, "shots": 3},
                    ],
                    "defense": [{"playerId": 103, "shots": 2}],
                },
                "awayTeam": {
                    "forwards": [
                        {"playerId": 201, "shots": 4},
                        {"playerId": 202, "shots": 1},
                    ],
                    "defense": [{"playerId": 203, "shots": 2}],
                },
            }
        },
    }


def pbp():
    return {
        "id": 2025020001,
        "plays": [
            {
                "typeDescKey": "goal",
                "periodDescriptor": {"number": 1},
                "details": {
                    "eventOwnerTeamId": 1,
                    "scoringPlayerId": 101,
                    "assist1PlayerId": 102,
                    "assist2PlayerId": 103,
                },
            },
            {
                "typeDescKey": "goal",
                "periodDescriptor": {"number": 2},
                "details": {
                    "eventOwnerTeamId": 2,
                    "scoringPlayerId": 201,
                    "assist1PlayerId": 202,
                },
            },
            {
                "typeDescKey": "goal",
                "periodDescriptor": {"number": 4},
                "details": {
                    "eventOwnerTeamId": 1,
                    "scoringPlayerId": 101,
                    "assist1PlayerId": 102,
                },
            },
        ],
    }


def observations():
    return build_official_player_role_observations(
        boxscore_payload=boxscore(),
        pbp_payload=pbp(),
        boxscore_captured_at="2025-10-02T03:00:00+00:00",
        pbp_captured_at="2025-10-02T03:01:00+00:00",
        boxscore_raw_sha256="a" * 64,
        pbp_raw_sha256="b" * 64,
    )


def test_official_role_source_combines_boxscore_sog_with_regulation_goal_assists():
    rows = observations()
    assert len(rows) == 6
    by_id = {r.player_id: r for r in rows}
    assert by_id["101"].shots_on_goal == 5
    assert by_id["101"].goals == 1  # OT goal excluded from regulation role history
    assert by_id["102"].primary_assists == 1
    assert by_id["103"].secondary_assists == 1
    assert by_id["201"].goals == 1
    assert by_id["202"].primary_assists == 1
    assert all(r.settled_at == "2025-10-02T03:01:00+00:00" for r in rows)
    assert all("joint=" in r.source_version for r in rows)


def test_official_role_history_binds_into_coherent_assist_market_paths():
    shares = fit_empirical_role_shares(
        observations(),
        cutoff="2026-09-29T12:00:00+00:00",
        team_id="1",
        version="official-role-v1",
        min_games=1,
    )
    bound = bind_historical_roles(
        shares,
        team="HOME",
        lineup_status="CONFIRMED",
        active_player_ids={"101", "102", "103"},
    )
    game = NHLGamePaths(
        home_regulation=(1, 2, 3, 1),
        away_regulation=(0, 1, 1, 2),
        home_final=(1, 2, 3, 1),
        away_final=(0, 1, 1, 2),
        seed=123,
    )
    paths = simulate_bound_roster_events(
        game,
        bound,
        team="HOME",
        puck_drop="2026-10-01T23:00:00+00:00",
        version="events-v1",
        seed=7,
    )
    win, push, loss = roster_event_over(paths.events, player_id="102", stat="assists", line=0.5)
    assert abs(win + push + loss - 1.0) < 1e-12
    assert win > 0


def test_official_role_source_rejects_cross_game_payloads():
    bad = pbp()
    bad["id"] = 2025029999
    try:
        build_official_player_role_observations(
            boxscore_payload=boxscore(),
            pbp_payload=bad,
            boxscore_captured_at="2025-10-02T03:00:00+00:00",
            pbp_captured_at="2025-10-02T03:01:00+00:00",
            boxscore_raw_sha256="a" * 64,
            pbp_raw_sha256="b" * 64,
        )
    except ValueError as exc:
        assert "identity mismatch" in str(exc)
    else:
        raise AssertionError("cross-game official sources must fail closed")
