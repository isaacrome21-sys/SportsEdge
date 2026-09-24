import pytest
from sportsedge.sports.nhl.role_history import (
    NHLPlayerGameRoleObservation, eligible_role_history,
    fit_empirical_role_shares, role_history_sha256,
)


def obs(game, player, settled, sog=2, goals=0, pa=0, sa=0, team="CHI"):
    return NHLPlayerGameRoleObservation(
        game, player, team, "2026-01-01T01:00:00Z", settled,
        "fixture", "v1", sog, goals, pa, sa,
    )


def test_cutoff_excludes_history_not_settled_before_target():
    rows = [
        obs("g1", "a", "2026-01-01T04:00:00Z", sog=3),
        obs("g2", "a", "2026-01-03T04:00:00Z", sog=9),
    ]
    eligible = eligible_role_history(rows, cutoff="2026-01-02T12:00:00Z", team_id="CHI")
    assert [r.game_id for r in eligible] == ["g1"]
    shares = fit_empirical_role_shares(rows, cutoff="2026-01-02T12:00:00Z", team_id="CHI", version="raw-v1")
    assert len(shares) == 1
    assert shares[0].shot_weight == 3.0


def test_role_weights_are_transparent_per_game_empirical_rates():
    rows = [
        obs("g1", "a", "2026-01-01T04:00:00Z", sog=4, goals=1, pa=1),
        NHLPlayerGameRoleObservation("g2", "a", "CHI", "2026-01-02T01:00:00Z",
            "2026-01-02T04:00:00Z", "fixture", "v1", 2, 0, 1, 2),
    ]
    share = fit_empirical_role_shares(rows, cutoff="2026-01-03T00:00:00Z", team_id="CHI", version="raw-v1")[0]
    assert (share.games, share.shot_weight, share.goal_weight) == (2, 3.0, 0.5)
    assert (share.primary_assist_weight, share.secondary_assist_weight) == (1.0, 1.0)


def test_history_digest_is_order_invariant_and_team_filter_isolated():
    a = obs("g1", "a", "2026-01-01T04:00:00Z")
    b = NHLPlayerGameRoleObservation("g2", "b", "DET", "2026-01-02T01:00:00Z",
        "2026-01-02T04:00:00Z", "fixture", "v1", 5, 1, 0, 0)
    assert role_history_sha256([a, b]) == role_history_sha256([b, a])
    shares = fit_empirical_role_shares([a, b], cutoff="2026-01-03T00:00:00Z", team_id="CHI", version="raw-v1")
    assert [x.player_id for x in shares] == ["a"]


def test_invalid_settlement_and_min_games_fail_closed():
    with pytest.raises(ValueError):
        obs("g1", "a", "2025-12-31T23:00:00Z")
    rows = [obs("g1", "a", "2026-01-01T04:00:00Z")]
    assert fit_empirical_role_shares(rows, cutoff="2026-01-02T00:00:00Z", team_id="CHI", version="raw-v1", min_games=2) == ()
